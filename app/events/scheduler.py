import asyncio
import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import discord
from discord.ext import commands, tasks
from sqlalchemy import select

from app import create_app
from app.core.config import settings
from app.database import db
from app.database.advanced_models import AnnouncementLog
from app.database.event_models import Event
from app.events.announcements import format_event
from app.events.feature_service import get_setting, set_setting
from app.events.rsvp import EventRSVPView

logger = logging.getLogger("kaplumbik.scheduler")
TR = ZoneInfo("Europe/Istanbul")


def _read_setting(key, default=""):
    app = create_app()
    with app.app_context():
        return get_setting(key, default)


def _due_events(now):
    app = create_app()
    with app.app_context():
        return list(db.session.execute(
            select(Event).where(Event.status == "scheduled", Event.starts_at >= now - timedelta(minutes=20), Event.starts_at <= now + timedelta(days=2))
        ).scalars())


def _already_sent(event_id, kind):
    row = db.session.execute(select(AnnouncementLog.id).where(
        AnnouncementLog.event_id == event_id, AnnouncementLog.kind == kind, AnnouncementLog.success.is_(True)
    ).limit(1)).first()
    return row is not None


def _log_delivery(event_id, channel_id, kind, message, success, error=""):
    db.session.add(AnnouncementLog(event_id=event_id, channel_id=str(channel_id) if channel_id else None, kind=kind, message=message[:4000], success=success, error=error[:500] or None))
    db.session.commit()


def _reminder_kind(seconds, reminder_minutes):
    """Return the one reminder due at this offset before an event."""
    if 119 * 60 <= seconds <= 120 * 60:
        return "final_2h"
    for minutes in reminder_minutes:
        if (minutes * 60 - 30) <= seconds <= (minutes * 60 + 30):
            return f"reminder_{minutes}m"
    return None


def _event_announcement_message(event):
    """Use the owner's template verbatim, replacing only documented placeholders."""
    template = (_read_setting("event_announcement_template", "") or "").strip()
    if not template:
        return format_event(event) + "\n\nKatılımını aşağıdaki butonlardan bildir."

    starts_at = event.starts_at
    if starts_at.tzinfo is None:
        starts_at = starts_at.replace(tzinfo=timezone.utc)
    local_start = starts_at.astimezone(TR)

    def safe(value):
        return discord.utils.escape_mentions(str(value or ""))

    values = {
        "title": safe(event.title),
        "game": safe(event.game),
        "time": local_start.strftime("%d.%m.%Y %H:%M"),
        "description": safe(event.description),
        "link": safe(event.game_link),
        "room_code": "",
    }
    message = template
    for key, value in values.items():
        message = message.replace("{" + key + "}", value)
    # Preserve the owner's layout and wording; only replace the documented placeholders.
    return message[:1850]


class EventScheduler(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._channel_alerted = False
        self.scheduler_loop.start()

    def cog_unload(self):
        self.scheduler_loop.cancel()

    async def _notify_admin(self, details: str):
        owner_id = await asyncio.to_thread(_read_setting, "designer_discord_id")
        if not owner_id or not owner_id.isdigit():
            owner_id = settings.owner_discord_id
        if not owner_id or not owner_id.isdigit():
            return
        try:
            user = self.bot.get_user(int(owner_id)) or await self.bot.fetch_user(int(owner_id))
            await user.send(f"⚠️ **Kaplumbik duyuru hatası**\n{details[:1200]}")
        except Exception:
            logger.exception("Could not send private admin alert")

    async def _channel(self):
        channel_id = await asyncio.to_thread(_read_setting, "game_announcement_channel_id")
        if not channel_id:
            channel_id = await asyncio.to_thread(_read_setting, "announcement_channel_id")
        if not channel_id or not channel_id.isdigit():
            if not self._channel_alerted:
                self._channel_alerted = True
                await self._notify_admin("Duyuru kanalı ayarlanmamış. Gelişmiş panelden duyuru kanalı ID'sini kaydet.")
            return None
        channel = self.bot.get_channel(int(channel_id))
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(int(channel_id))
            except Exception as exc:
                logger.exception("Announcement channel unavailable")
                if not self._channel_alerted:
                    self._channel_alerted = True
                    await self._notify_admin(f"Duyuru kanalına erişilemiyor: {exc}")
                return None
        self._channel_alerted = False
        return channel

    @tasks.loop(minutes=1)
    async def scheduler_loop(self):
        await self.bot.wait_until_ready()
        channel = await self._channel()
        if channel is None:
            return
        await self._process_resend(channel)
        now = datetime.now(timezone.utc)
        try:
            events = await asyncio.to_thread(_due_events, now)
            for event in events:
                starts_at = event.starts_at
                if starts_at.tzinfo is None:
                    starts_at = starts_at.replace(tzinfo=timezone.utc)
                seconds = (starts_at - now).total_seconds()
                reminder_raw = await asyncio.to_thread(_read_setting, "game_reminder_minutes", "15,5")
                try:
                    reminder_minutes = [int(x.strip()) for x in reminder_raw.split(",") if x.strip()]
                    reminder_minutes = [minutes for minutes in reminder_minutes if 1 <= minutes <= 1440]
                except ValueError:
                    reminder_minutes = [15, 5]
                kind = _reminder_kind(seconds, reminder_minutes)
                if not kind:
                    continue
                app = create_app()
                with app.app_context():
                    if _already_sent(event.id, kind):
                        continue
                game_name = event.game.casefold()
                if not event.game_link:
                    if "minecraft" in game_name or "realms" in game_name:
                        event.game_link = await asyncio.to_thread(_read_setting, "minecraft_realms_link")
                    elif "gartic" in game_name:
                        event.game_link = await asyncio.to_thread(_read_setting, "gartic_phone_link")
                if not event.room_code and "among us" in game_name:
                    event.room_code = await asyncio.to_thread(_read_setting, "among_us_room_code")
                ping = (await asyncio.to_thread(_read_setting, "announcement_everyone_ping", "true")).lower() == "true"
                prefix = "@everyone\n" if ping else ""
                message = prefix + _event_announcement_message(event)
                try:
                    await channel.send(message, view=EventRSVPView(event.id), allowed_mentions=discord.AllowedMentions(everyone=ping, users=False, roles=False))
                    app = create_app()
                    with app.app_context():
                        _log_delivery(event.id, channel.id, kind, message, True)
                except Exception as exc:
                    logger.exception("Event announcement failed")
                    app = create_app()
                    with app.app_context():
                        _log_delivery(event.id, channel.id, kind, message, False, str(exc))
                    await self._notify_admin(f"Etkinlik #{event.id} duyurusu gönderilemedi: {exc}")
        except Exception as exc:
            logger.exception("Scheduler loop failed")
            await self._notify_admin(f"Zamanlayıcı döngüsü hata verdi: {exc}")

        await self._daily_announcement(channel)

    async def _process_resend(self, channel):
        event_id = await asyncio.to_thread(_read_setting, "resend_event_id")
        if not event_id or not event_id.isdigit():
            return
        app = create_app()
        with app.app_context():
            event = db.session.get(Event, int(event_id))
        if event is None or event.status != "scheduled":
            app = create_app()
            with app.app_context():
                set_setting("resend_event_id", "")
            await self._notify_admin(f"Yeniden gönderim isteğindeki etkinlik bulunamadı veya planlanmış değil: #{event_id}")
            return
        game_name = event.game.casefold()
        if not event.game_link:
            if "minecraft" in game_name or "realms" in game_name:
                event.game_link = await asyncio.to_thread(_read_setting, "minecraft_realms_link")
            elif "gartic" in game_name:
                event.game_link = await asyncio.to_thread(_read_setting, "gartic_phone_link")
        if not event.room_code and "among us" in game_name:
            event.room_code = await asyncio.to_thread(_read_setting, "among_us_room_code")
        ping = (await asyncio.to_thread(_read_setting, "announcement_everyone_ping", "true")).lower() == "true"
        message = ("@everyone\n" if ping else "") + _event_announcement_message(event)
        kind = f"manual_resend:{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
        try:
            await channel.send(message, view=EventRSVPView(event.id), allowed_mentions=discord.AllowedMentions(everyone=ping, users=False, roles=False))
            app = create_app()
            with app.app_context():
                _log_delivery(event.id, channel.id, kind, message, True)
                set_setting("resend_event_id", "")
        except Exception as exc:
            logger.exception("Manual announcement resend failed")
            app = create_app()
            with app.app_context():
                _log_delivery(event.id, channel.id, kind, message, False, str(exc))
                set_setting("resend_event_id", "")
            await self._notify_admin(f"Etkinlik #{event.id} yeniden gönderilemedi: {exc}")

    async def _daily_announcement(self, channel):
        local_now = datetime.now(TR)
        times = await asyncio.to_thread(_read_setting, "announcement_times", "12:00,17:00,20:00")
        current_slot = local_now.strftime("%H:%M")
        if current_slot not in [x.strip() for x in times.split(",")]:
            return
        kind = f"daily:{local_now.strftime('%Y-%m-%d')}:{current_slot}"
        app = create_app()
        with app.app_context():
            exists = db.session.execute(select(AnnouncementLog.id).where(AnnouncementLog.kind == kind, AnnouncementLog.success.is_(True)).limit(1)).first()
            if exists:
                return
        # Send the owner's exact dashboard-written text; never let AI rewrite announcements.
        custom_text = (await asyncio.to_thread(_read_setting, "daily_announcement_text", "")).strip()
        if not custom_text:
            return
        ping = (await asyncio.to_thread(_read_setting, "announcement_everyone_ping", "true")).lower() == "true"
        text = ("@everyone\n" if ping else "") + custom_text
        try:
            await channel.send(text, allowed_mentions=discord.AllowedMentions(everyone=ping, users=False, roles=False))
            app = create_app()
            with app.app_context():
                _log_delivery(None, channel.id, kind, text, True)
        except Exception as exc:
            logger.exception("Daily announcement failed")
            app = create_app()
            with app.app_context():
                _log_delivery(None, channel.id, kind, text, False, str(exc))
            await self._notify_admin(f"Genel duyuru gönderilemedi: {exc}")


async def setup(bot: commands.Bot):
    await bot.add_cog(EventScheduler(bot))

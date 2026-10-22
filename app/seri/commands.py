"""Commands and listener for Mahzen's shared daily streak."""
import logging
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from discord.ext import commands, tasks
from sqlalchemy import select

from app import create_app
from app.core.config import settings
from app.database import db
from app.database.advanced_models import BotSetting
from app.database.models import AuditLog
from app.seri.models import StreakContribution, StreakDay
from app.seri.service import (
    GOAL, close_day, contribution_count, correct_contribution, get_channel_id,
    get_or_create_day, get_source_channel_ids, latest_streak_length, make_up_pending_days,
    record_contribution, set_channel_id, set_source_channel,
)

logger = logging.getLogger("kaplumbik.seri")
TZ = ZoneInfo("Europe/Istanbul")


def local_today() -> date:
    return datetime.now(TZ).date()


def _setting(key: str) -> str:
    row = db.session.get(BotSetting, key)
    return (row.value or "").strip() if row else ""


def _set_setting(key: str, value: str) -> None:
    row = db.session.get(BotSetting, key)
    if row is None:
        row = BotSetting(key=key, value=value)
        db.session.add(row)
    else:
        row.value = value
    db.session.commit()


def _is_owner(interaction: discord.Interaction) -> bool:
    return bool(settings.owner_discord_id) and str(interaction.user.id) == str(settings.owner_discord_id)


def _is_owner_or_admin(interaction: discord.Interaction) -> bool:
    return _is_owner(interaction) or bool(
        isinstance(interaction.user, discord.Member)
        and interaction.user.guild_permissions.administrator
    )


class SharedStreak(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._started = False
        self._history_backfilled = False

    async def cog_load(self):
        app = create_app()
        with app.app_context():
            if not _setting("streak_tracking_started_date"):
                _set_setting("streak_tracking_started_date", local_today().isoformat())
        if not self.daily_closure.is_running():
            self.daily_closure.start()

    def cog_unload(self):
        self.daily_closure.cancel()


    @commands.Cog.listener()
    async def on_ready(self):
        if self._history_backfilled:
            return
        self._history_backfilled = True
        try:
            await self._backfill_accessible_history()
        except Exception:
            logger.exception("Seri geçmişini bot açılışında taramak başarısız oldu.")

    async def _backfill_accessible_history(self):
        app=create_app()
        with app.app_context():
            source_ids=get_source_channel_ids()
            last_value=_setting("streak_last_closed_date")
            start_value=_setting("streak_tracking_started_date")
            start_day=date.fromisoformat(last_value)+timedelta(days=1) if last_value else (date.fromisoformat(start_value) if start_value else local_today())
            output_id=get_channel_id()
        if not source_ids or not output_id:
            return
        today=local_today()
        if start_day>today:
            return
        after=datetime.combine(start_day,datetime.min.time(),tzinfo=TZ).astimezone(timezone.utc)
        before=datetime.now(timezone.utc)
        contributions={}
        for channel_id in source_ids:
            channel=self.bot.get_channel(int(channel_id))
            if channel is None:
                try: channel=await self.bot.fetch_channel(int(channel_id))
                except discord.HTTPException:
                    logger.warning("Seri geçmişi taranamadı; kanal erişilemiyor: %s",channel_id); continue
            if not hasattr(channel,"history"):
                continue
            try:
                async for message in channel.history(limit=None,after=after,before=before,oldest_first=True):
                    if message.guild is None or message.author.bot or message.webhook_id is not None:
                        continue
                    day=message.created_at.astimezone(TZ).date()
                    if day<start_day or day>today:
                        continue
                    key=(day,str(message.author.id))
                    contributions.setdefault(key,(str(channel.id),str(message.id)))
            except (discord.Forbidden,discord.HTTPException):
                logger.exception("Seri geçmişi okunamadı: channel=%s",channel_id)
        app=create_app()
        with app.app_context():
            changed_days=set()
            for (day,discord_id),(channel_id,message_id) in contributions.items():
                _,added=record_contribution(day,discord_id,channel_id,message_id)
                if added: changed_days.add(day)
            if changed_days:
                logger.info("Seri geçmişinden %s katkı kaydı geri kazanıldı.",len(changed_days))
            today_row=db.session.execute(select(StreakDay).where(StreakDay.day==today.isoformat())).scalar_one_or_none()
            output_channel=self.bot.get_channel(int(output_id))
        if today_row and output_channel:
            await self._update_progress(output_channel,today_row)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.guild is None or message.author.bot or message.webhook_id is not None:
            return
        app = create_app()
        with app.app_context():
            source_channels = get_source_channel_ids()
            output_channel_id = get_channel_id()
            if not source_channels or str(message.channel.id) not in source_channels or not output_channel_id:
                return
            today = local_today()
            row, added = record_contribution(
                today, str(message.author.id), str(message.channel.id), str(message.id)
            )
            if added:
                output_channel = self.bot.get_channel(int(output_channel_id))
                if output_channel is None:
                    try:
                        output_channel = await self.bot.fetch_channel(int(output_channel_id))
                    except discord.HTTPException:
                        logger.exception("Seri çıktı kanalı alınamadı.")
                        return
                await self._update_progress(output_channel, row)

    async def _update_progress(self, channel, day_row: StreakDay):
        app = create_app()
        with app.app_context():
            count = contribution_count(day_row)
            ids = list(db.session.execute(select(StreakContribution.discord_id)
                .where(StreakContribution.day_id == day_row.id)
                .order_by(StreakContribution.first_message_at.asc())).scalars())
            message_id = day_row.progress_message_id
            paused = db.session.execute(select(StreakDay.id).where(
                StreakDay.day < day_row.day, StreakDay.status == "pending"
            ).limit(1)).scalar_one_or_none() is not None
        names = " ".join(f"<@{member_id}>" for member_id in ids)
        if count >= GOAL:
            if paused:
                content = f"🐢 **Günlük hedef tamamlandı!** ({count}/{GOAL})\nSeri, önceki günler için telafi beklediğinden duraklatıldı.\n{names}"
            else:
                content = f"🎉 **Mahzen serisi hedefi tamamlandı!** ({count}/{GOAL})\nKatkı verenler: {names}"
        else:
            content = f"🐢 **Mahzen ortak serisi** · {count}/{GOAL} farklı üye\nBugünkü hedef için {max(0, GOAL-count)} üye daha gerekiyor.\nKatkı verenler: {names or 'Henüz kimse yok.'}"
        try:
            target = await channel.fetch_message(int(message_id)) if message_id else None
            if target:
                await target.edit(content=content, allowed_mentions=discord.AllowedMentions.none())
            else:
                target = await channel.send(content, allowed_mentions=discord.AllowedMentions.none())
                with app.app_context():
                    fresh = db.session.execute(select(StreakDay).where(StreakDay.day == day_row.day)).scalar_one()
                    fresh.progress_message_id = str(target.id)
                    db.session.commit()
        except discord.HTTPException:
            logger.exception("Seri ilerleme mesajı güncellenemedi.")

    @tasks.loop(minutes=1)
    async def daily_closure(self):
        now = datetime.now(TZ)
        if now.hour != 0 or now.minute < 5:
            return
        app = create_app()
        with app.app_context():
            today = now.date()
            yesterday = today - timedelta(days=1)
            start_value = _setting("streak_tracking_started_date")
            if not start_value:
                _set_setting("streak_tracking_started_date", today.isoformat())
                return
            start_day = date.fromisoformat(start_value)
            last_value = _setting("streak_last_closed_date")
            cursor = date.fromisoformat(last_value) + timedelta(days=1) if last_value else start_day
            channel_value = get_channel_id()
        if not channel_value:
            return
        channel = self.bot.get_channel(int(channel_value))
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(int(channel_value))
            except (discord.HTTPException, ValueError):
                logger.error("Seri kanalı bulunamadı veya erişilemiyor: %s", channel_value)
                return
        while cursor <= yesterday:
            app = create_app()
            with app.app_context():
                day_row, _ = close_day(cursor)
                summary_id = day_row.summary_message_id
                count = contribution_count(day_row)
                status = day_row.status
                streak = latest_streak_length()
                ids = list(db.session.execute(select(StreakContribution.discord_id)
                    .where(StreakContribution.day_id == day_row.id)
                    .order_by(StreakContribution.first_message_at.asc())).scalars())
            if not summary_id:
                names = " ".join(f"<@{member_id}>" for member_id in ids) or "Katkı yok."
                if status == "completed":
                    status_text = "Hedef tamamlandı ✅"
                else:
                    status_text = "Hedef tamamlanmadı veya önceki telafi bekleyen günler var; seri duraklatıldı ⏸️"
                content = (f"📊 **Mahzen seri gün özeti · {cursor.strftime('%d.%m.%Y')}**\n"
                    f"{status_text}\nKatkı veren farklı üye: **{count}**/{GOAL}\n"
                    f"Mevcut seri uzunluğu: **{streak} gün**\nKatkıda bulunanlar: {names}")
                try:
                    sent = await channel.send(content, allowed_mentions=discord.AllowedMentions.none())
                except discord.HTTPException:
                    logger.exception("Seri günlük özeti gönderilemedi: %s", cursor)
                    return
                with app.app_context():
                    fresh = db.session.execute(select(StreakDay).where(StreakDay.day == cursor.isoformat())).scalar_one()
                    fresh.summary_message_id = str(sent.id)
                    db.session.commit()
            with app.app_context():
                _set_setting("streak_last_closed_date", cursor.isoformat())
            cursor += timedelta(days=1)

    @daily_closure.before_loop
    async def before_daily_closure(self):
        await self.bot.wait_until_ready()

    @app_commands.command(name="seri", description="Mahzen'in ortak seri durumunu göster.")
    async def streak_status(self, interaction: discord.Interaction):
        app = create_app()
        with app.app_context():
            today = local_today()
            row = get_or_create_day(today)
            count = contribution_count(row)
            pending = list(db.session.execute(select(StreakDay).where(StreakDay.status == "pending")
                .order_by(StreakDay.day.asc())).scalars())
            streak = latest_streak_length()
            channel_id = get_channel_id()
            db.session.commit()
        channel_text = f"<#{channel_id}>" if channel_id else "Henüz ayarlanmamış"
        app = create_app()
        with app.app_context():
            source_ids = sorted(get_source_channel_ids(), key=int)
        source_text = ", ".join(f"<#{item}>" for item in source_ids) or "Henüz ayarlanmamış"
        pending_text = ", ".join(day.day for day in pending[-10:]) or "Yok"
        await interaction.response.send_message(
            f"🐢 **Mahzen ortak serisi**\nBugün: **{count}/{GOAL}** farklı üye\n"
            f"Mevcut seri: **{streak} gün**\nTelafi bekleyen günler: {pending_text}\nSeri kanalı: {channel_text}\nSayılacak sohbet kanalları: {source_text}",
            ephemeral=False, allowed_mentions=discord.AllowedMentions.none(),
        )

    @app_commands.command(name="serikanal", description="Ortak seri mesajlarının gönderileceği kanalı ayarla.")
    @app_commands.describe(kanal="Seri ilerlemesi ve günlük özetlerin gönderileceği metin kanalı")
    async def streak_channel(self, interaction: discord.Interaction, kanal: discord.TextChannel):
        if not _is_owner_or_admin(interaction):
            await interaction.response.send_message("Bu işlem sunucu sahibi veya Administrator yetkisi gerektirir.", ephemeral=True)
            return
        permissions = kanal.permissions_for(interaction.guild.me) if interaction.guild and interaction.guild.me else None
        if permissions is None or not permissions.view_channel or not permissions.send_messages or not permissions.read_message_history:
            await interaction.response.send_message("Botun bu kanalda Görüntüle, Mesaj Gönder ve Mesaj Geçmişini Oku izinleri olmalı.", ephemeral=True)
            return
        app = create_app()
        with app.app_context():
            set_channel_id(str(kanal.id), str(interaction.user.id))
        await interaction.response.send_message(f"Seri ilerlemesi ve özet kanalı {kanal.mention} olarak ayarlandı.", ephemeral=True)

    @app_commands.command(name="serikaynakkanal", description="Ortak seri sayacına katkı sağlayan sohbet kanalını ekle veya çıkar.")
    @app_commands.describe(kanal="Mesajları sayılacak sohbet kanalı", ekle="True: ekle, False: çıkar")
    async def streak_source_channel(self, interaction: discord.Interaction, kanal: discord.TextChannel, ekle: bool):
        if not _is_owner_or_admin(interaction):
            await interaction.response.send_message("Bu işlem sunucu sahibi veya Administrator yetkisi gerektirir.", ephemeral=True)
            return
        permissions = kanal.permissions_for(interaction.guild.me) if interaction.guild and interaction.guild.me else None
        if ekle and (permissions is None or not permissions.view_channel or not permissions.read_message_history):
            await interaction.response.send_message("Botun bu kaynak kanalını görüntüleme ve mesaj geçmişini okuma izinleri olmalı.", ephemeral=True)
            return
        app = create_app()
        with app.app_context():
            channels = set_source_channel(str(kanal.id), ekle, str(interaction.user.id))
        action = "eklendi" if ekle else "çıkarıldı"
        channel_list = ", ".join(f"<#{item}>" for item in sorted(channels, key=int)) or "Hiç kaynak kanalı yok"
        await interaction.response.send_message(f"{kanal.mention} kaynak listesinden {action}.\nKaynak kanallar: {channel_list}", ephemeral=True, allowed_mentions=discord.AllowedMentions.none())

    @app_commands.command(name="seritelafi", description="En eski değil, en son telafi bekleyen günleri telafi et.")
    @app_commands.describe(gun_sayisi="Telafi edilecek son bekleyen gün sayısı")
    async def streak_make_up(self, interaction: discord.Interaction, gun_sayisi: app_commands.Range[int, 1, 365]):
        if not _is_owner_or_admin(interaction):
            await interaction.response.send_message("Telafi yalnızca sunucu sahibi veya Administrator yetkilisine açıktır.", ephemeral=True)
            return
        app = create_app()
        try:
            with app.app_context():
                days = make_up_pending_days(int(gun_sayisi), str(interaction.user.id))
                labels = ", ".join(row.day for row in days)
            await interaction.response.send_message(f"✅ Telafi kaydedildi: {labels}. Seri geçmişi yeniden hesaplandı.", allowed_mentions=discord.AllowedMentions.none())
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)

    @app_commands.command(name="serikatkiduzelt", description="Bir üyenin seri katkısını düzelt (yalnızca sahip).")
    @app_commands.describe(tarih="YYYY-MM-DD", uye="Katkısı düzeltilecek üye", ekle="True ise katkı ekle, False ise kaldır", gerekce="Zorunlu denetim gerekçesi")
    async def streak_correct(self, interaction: discord.Interaction, tarih: str, uye: discord.Member, ekle: bool, gerekce: app_commands.Range[str, 3, 300]):
        if not _is_owner(interaction):
            await interaction.response.send_message("Katkı düzeltme yalnızca sunucu sahibine açıktır.", ephemeral=True)
            return
        try:
            parsed = date.fromisoformat(tarih)
        except ValueError:
            await interaction.response.send_message("Tarih YYYY-MM-DD biçiminde olmalı.", ephemeral=True)
            return
        app = create_app()
        try:
            with app.app_context():
                count = correct_contribution(parsed, str(uye.id), ekle, str(interaction.user.id), gerekce)
            await interaction.response.send_message(f"Katkı düzeltildi. {tarih} için toplam farklı üye: {count}/{GOAL}.", ephemeral=True)
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(SharedStreak(bot))

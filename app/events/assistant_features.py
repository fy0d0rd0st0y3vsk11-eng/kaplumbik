import asyncio
import logging
from datetime import datetime, timezone

import discord
import requests
from discord.ext import commands, tasks

from app import create_app
from app.core.config import settings
from app.database import db
from app.database.advanced_models import AnnouncementLog
from app.database.event_models import Event
from app.events.announcements import format_event
from app.events.feature_service import get_setting, record_health

logger = logging.getLogger("kaplumbik.features")


def _setting(key: str, default: str = "") -> str:
    app = create_app()
    with app.app_context():
        return get_setting(key, default)


def _health(component: str, status: str, details: str = ""):
    app = create_app()
    with app.app_context():
        record_health(component, status, details)


def _next_game_link():
    from datetime import datetime, timezone
    from sqlalchemy import select
    app = create_app()
    with app.app_context():
        event = db.session.execute(select(Event).where(Event.status == "scheduled", Event.starts_at >= datetime.now(timezone.utc)).order_by(Event.starts_at.asc()).limit(1)).scalar_one_or_none()
        if event is None:
            return None
        game = event.game.casefold()
        link = event.game_link
        if not link and ("minecraft" in game or "realms" in game):
            link = get_setting("minecraft_realms_link")
        elif not link and "gartic" in game:
            link = get_setting("gartic_phone_link")
        if "among us" in game and not link:
            code = event.room_code or get_setting("among_us_room_code")
            return (event.game, f"Oda kodu: {code}") if code else (event.game, None)
        return (event.game, link)


async def _notify_owner(bot: commands.Bot, details: str):
    owner_id = await asyncio.to_thread(_setting, "designer_discord_id")
    if not owner_id or not owner_id.isdigit():
        owner_id = settings.owner_discord_id
    if not owner_id or not owner_id.isdigit():
        return
    try:
        user = bot.get_user(int(owner_id)) or await bot.fetch_user(int(owner_id))
        await user.send(f"⚠️ **Kaplumbik hata bildirimi**\n{details[:1500]}")
    except Exception:
        logger.exception("Could not send private admin alert")


def _ai_request(prompt: str, personality: str) -> str:
    if not settings.openrouter_api_key:
        raise RuntimeError("OPENROUTER_API_KEY ayarlanmamış.")
    response = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {settings.openrouter_api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/fy0d0rd0st0y3vsk11-eng/kaplumbik",
            "X-Title": "Kaplumbik",
        },
        json={
            "model": settings.openrouter_model or "openai/gpt-4o-mini",
            "messages": [
                {"role": "system", "content": personality[:6000]},
                {"role": "user", "content": prompt[:3000]},
            ],
            "temperature": 0.7,
            "max_tokens": 450,
        },
        timeout=20,
    )
    response.raise_for_status()
    data = response.json()
    return data["choices"][0]["message"]["content"].strip()[:1900]


class AssistantFeatures(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.health_loop.start()

    def cog_unload(self):
        self.health_loop.cancel()

    @tasks.loop(minutes=5)
    async def health_loop(self):
        await self.bot.wait_until_ready()
        try:
            await asyncio.to_thread(_health, "discord", "ok", f"Bot çevrimiçi: {self.bot.user}")
        except Exception:
            logger.exception("Health record failed")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return
        content = message.content.strip()
        lowered = content.casefold()
        if not content:
            return

        if any(term in lowered for term in ("realms link", "realms bağlantı", "realms linki", "minecraft link")):
            link = await asyncio.to_thread(_setting, "minecraft_realms_link")
            if link:
                await message.reply(f"🌍 Minecraft Realms bağlantısı: {link}", mention_author=False, allowed_mentions=discord.AllowedMentions.none())
            else:
                await message.reply("Minecraft Realms bağlantısı henüz yönetim paneline eklenmemiş.", mention_author=False)
            return
        if any(term in lowered for term in ("gartic link", "gartic phone link", "gartic bağlantı")):
            link = await asyncio.to_thread(_setting, "gartic_phone_link")
            await message.reply(f"🎨 Gartic Phone bağlantısı: {link}" if link else "Gartic Phone bağlantısı henüz ayarlanmamış.", mention_author=False, allowed_mentions=discord.AllowedMentions.none())
            return
        if any(term in lowered for term in ("among us kod", "among us code", "oda kodu", "code?")):
            code = await asyncio.to_thread(_setting, "among_us_room_code")
            await message.reply(f"🚀 Among Us oda kodu: **{code}**" if code else "Among Us oda kodu henüz ayarlanmamış.", mention_author=False, allowed_mentions=discord.AllowedMentions.none())
            return

        if lowered.strip() in {"link", "link?", "link pls", "linki at", "link at", "bağlantı", "bağlantı?", "linki"}:
            result = await asyncio.to_thread(_next_game_link)
            if result and result[1]:
                await message.reply(f"🔗 Yaklaşan {result[0]} etkinliği: {result[1]}", mention_author=False, allowed_mentions=discord.AllowedMentions.none())
            elif result:
                await message.reply(f"Yaklaşan {result[0]} etkinliği için bağlantı/kod henüz ayarlanmamış.", mention_author=False)
            else:
                await message.reply("Şu anda yaklaşan etkinlik yok.", mention_author=False)
            return

        if self.bot.user and self.bot.user in message.mentions:
            if any(term in lowered for term in ("realms'e nasıl", "realms'e nasil", "realms nasıl katıl", "realms nasil katil", "minecraft realms", "how do i join realms", "how do i join a realm", "how to join realms", "join my realm")):
                await message.reply(
                    "Minecraft Realms'e katılmak için: Minecraft'ı aç, doğru Microsoft hesabında olduğundan emin ol, **Oyna > Arkadaşlar** bölümüne gir ve davet edilen Realm'i seç. Sahip sana davet bağlantısı/kodu göndermeli; sürümün (Bedrock/Java) ve platformun Realm ile uyumlu olmalı. Bağlantıyı panelden ekleyebiliriz.",
                    mention_author=False,
                )
                return
            try:
                personality = await asyncio.to_thread(_setting, "ai_personality")
                answer = await asyncio.to_thread(_ai_request, content, personality)
                await message.reply(answer, mention_author=False, allowed_mentions=discord.AllowedMentions.none())
                await asyncio.to_thread(_health, "ai", "ok", "AI yanıtı üretildi.")
            except Exception as exc:
                logger.exception("AI response failed")
                await asyncio.to_thread(_health, "ai", "error", str(exc))
                await _notify_owner(self.bot, f"AI yanıtı başarısız: {str(exc)}")
                await message.reply("Şu an yanıt veremedim; hata yönetim paneline kaydedildi.", mention_author=False)

    @commands.command(name="kimtasarladi", aliases=["tasarlayan", "designer"])
    async def designer(self, ctx: commands.Context):
        owner_id = await asyncio.to_thread(_setting, "designer_discord_id")
        if not owner_id or not owner_id.isdigit():
            owner_id = settings.owner_discord_id
        if owner_id and owner_id.isdigit():
            await ctx.send(f"🐢 Kaplumbik'i tasarlayan kişi: <@{owner_id}>", allowed_mentions=discord.AllowedMentions(users=[discord.Object(id=int(owner_id))], roles=False, everyone=False))
        else:
            await ctx.send("Tasarımcı Discord ID'si henüz yönetim panelinde ayarlanmamış.")

    @commands.command(name="tanit", aliases=["intro"])
    async def introduce_member(self, ctx: commands.Context, member: discord.Member):
        intro = await asyncio.to_thread(_setting, "new_member_intro")
        await ctx.send(f"👋 {member.mention} için Mahzen tanıtımı:\n{intro}", allowed_mentions=discord.AllowedMentions(users=[member], roles=False, everyone=False))

    @commands.command(name="profil")
    async def profile(self, ctx: commands.Context, member: discord.Member | None = None):
        member = member or ctx.author
        app = create_app()
        with app.app_context():
            from sqlalchemy import select
            from app.database.event_models import EventParticipation
            from app.database.models import UserProfile
            from app.database.advanced_models import AchievementDefinition
            profile = db.session.execute(select(UserProfile).where(UserProfile.discord_id == str(member.id))).scalar_one_or_none()
            participations = db.session.execute(select(EventParticipation).where(EventParticipation.discord_id == str(member.id), EventParticipation.status == "attended")).scalars().all()
            event_ids = [row.event_id for row in participations]
            games = {}
            last_event = None
            for event_id in event_ids:
                event = db.session.get(Event, event_id)
                if event:
                    games[event.game] = games.get(event.game, 0) + 1
                    if last_event is None or event.starts_at > last_event.starts_at:
                        last_event = event
            most_played = max(games, key=games.get) if games else "Henüz yok"
            balance = profile.balance if profile else 0
            min_points = int(get_setting("giveaway_min_points", "100"))
            achievement_defs = db.session.query(AchievementDefinition).filter_by(enabled=True).all()
            attended_events = [db.session.get(Event, event_id) for event_id in event_ids]
            attended_events = [event for event in attended_events if event is not None]
            starts = sorted(event.starts_at for event in attended_events)
            max_gap_days = max(((starts[i] - starts[i - 1]).days for i in range(1, len(starts))), default=0)
            earned = []
            for achievement in achievement_defs:
                if achievement.condition_type == "events_attended":
                    current = len(participations)
                elif achievement.condition_type == "unique_games":
                    current = len(games)
                elif achievement.condition_type == "points":
                    current = balance
                elif achievement.condition_type == "comeback_days":
                    current = max_gap_days
                else:
                    continue
                if current >= achievement.threshold:
                    earned.append(achievement.title)
        eligible = balance >= min_points
        embed = discord.Embed(title=f"📋 {member.display_name} · Kaplumbik profili", color=discord.Color.blurple())
        embed.add_field(name="Puan", value=str(balance), inline=True)
        embed.add_field(name="Katıldığı etkinlik", value=str(len(participations)), inline=True)
        embed.add_field(name="En çok oynadığı oyun", value=most_played, inline=True)
        embed.add_field(name="Son etkinlik", value=last_event.title if last_event else "Henüz yok", inline=False)
        embed.add_field(name="Rozetler", value=", ".join(earned) if earned else "Henüz rozet yok", inline=False)
        embed.add_field(name="Çekiliş uygunluğu", value="Uygun" if eligible else f"Uygun değil (en az {min_points} puan)", inline=False)
        await ctx.send(embed=embed)

    @commands.command(name="etkinlikgecmisi")
    async def event_history(self, ctx: commands.Context, event_id: int):
        app = create_app()
        with app.app_context():
            from app.database.event_models import EventParticipation
            rows = db.session.query(EventParticipation).filter_by(event_id=event_id).all()
            event = db.session.get(Event, event_id)
            if event is None:
                await ctx.send("Bu etkinlik bulunamadı.")
                return
            going = [f"<@{r.discord_id}>" for r in rows if r.status == "going"]
            not_going = [f"<@{r.discord_id}>" for r in rows if r.status == "not_going"]
            await ctx.send(f"**{event.title}**\nKatılacağım ({len(going)}): {', '.join(going) or 'yok'}\nKatılmayacağım ({len(not_going)}): {', '.join(not_going) or 'yok'}", allowed_mentions=discord.AllowedMentions.none())


async def setup(bot: commands.Bot):
    await bot.add_cog(AssistantFeatures(bot))

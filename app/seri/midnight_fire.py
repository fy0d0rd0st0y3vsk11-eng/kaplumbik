"""Midnight fire GIF for the shared Mahzen streak channel."""
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

import discord
from discord.ext import commands, tasks

from app import create_app
from app.database import db
from app.database.advanced_models import BotSetting
from app.seri.service import get_channel_id

logger = logging.getLogger("kaplumbik.seri.fire")
TZ = ZoneInfo("Europe/Istanbul")
FIRE_GIF_URL = "https://www.image2url.com/r2/default/gifs/1792763993696-e3670524-036b-4c84-abd9-f9f4e4d099b1.gif"
LAST_SENT_KEY = "streak_fire_last_sent_date"


def _last_sent_date() -> str:
    row = db.session.get(BotSetting, LAST_SENT_KEY)
    return (row.value or "").strip() if row else ""


def _save_sent_date(day: str) -> None:
    row = db.session.get(BotSetting, LAST_SENT_KEY)
    if row is None:
        db.session.add(BotSetting(key=LAST_SENT_KEY, value=day))
    else:
        row.value = day
    db.session.commit()


class MidnightFire(commands.Cog):
    """Send the owner's animated fire GIF once per Istanbul calendar day."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.midnight_fire_loop.start()

    def cog_unload(self):
        self.midnight_fire_loop.cancel()

    @tasks.loop(minutes=1)
    async def midnight_fire_loop(self):
        now = datetime.now(TZ)
        # A five-minute window makes this resilient to small scheduler delays
        # while the persistent date guard prevents repeated posts that night.
        if now.hour != 0 or now.minute > 4:
            return

        day_key = now.date().isoformat()
        app = create_app()
        with app.app_context():
            if _last_sent_date() == day_key:
                return
            channel_id = get_channel_id()

        if not channel_id:
            logger.warning("Midnight fire GIF skipped: seri output channel is not configured.")
            return

        channel = self.bot.get_channel(int(channel_id))
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(int(channel_id))
            except (discord.HTTPException, ValueError):
                logger.exception("Midnight fire GIF could not access channel %s", channel_id)
                return

        if not hasattr(channel, "send"):
            logger.error("Configured seri output ID is not a sendable channel: %s", channel_id)
            return

        try:
            # Keep the direct GIF URL in message content so Discord can render
            # the animated media preview instead of flattening it into an embed.
            await channel.send(
                FIRE_GIF_URL,
                allowed_mentions=discord.AllowedMentions.none(),
            )
            with app.app_context():
                _save_sent_date(day_key)
            logger.info("Midnight fire GIF sent for %s to channel %s", day_key, channel_id)
        except (discord.HTTPException, Exception):
            logger.exception("Midnight fire GIF delivery failed for %s", day_key)

    @midnight_fire_loop.before_loop
    async def before_midnight_fire_loop(self):
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot):
    await bot.add_cog(MidnightFire(bot))

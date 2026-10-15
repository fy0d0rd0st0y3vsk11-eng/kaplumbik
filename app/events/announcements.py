
import logging

import discord
from discord.ext import commands

from app.database.event_models import Event
from app.events.service import list_upcoming_events


logger = logging.getLogger("kaplumbik.events")


def format_event(event: Event) -> str:
    """Format an event for a Discord announcement."""

    starts_at = event.starts_at

    if starts_at.tzinfo is None:
        # Existing naive database values are treated as UTC.
        starts_at = starts_at.replace(
            tzinfo=__import__("datetime").timezone.utc
        )

    timestamp = int(starts_at.timestamp())

    lines = [
        f"🎮 **{discord.utils.escape_markdown(event.title)}**",
        f"🕹️ Oyun: {discord.utils.escape_markdown(event.game)}",
        f"🕒 Başlangıç: <t:{timestamp}:F>",
    ]

    if event.description:
        lines.append(
            discord.utils.escape_markdown(event.description)
        )

    if event.game_link:
        lines.append(f"🔗 Oyun bağlantısı: {event.game_link}")

    if event.room_code:
        lines.append(
            f"🔑 Oda kodu: {discord.utils.escape_markdown(event.room_code)}"
        )

    return "\n".join(lines)


class EventAnnouncementCog(commands.Cog):
    """Discord commands for displaying scheduled events."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.command(name="etkinlikler")
    async def upcoming_events(self, ctx: commands.Context):
        """List upcoming scheduled events."""

        try:
            events = list_upcoming_events(limit=10)

            if not events:
                await ctx.send("📭 Yaklaşan etkinlik bulunmuyor.")
                return

            for event in events:
                await ctx.send(
                    format_event(event),
                    allowed_mentions=discord.AllowedMentions.none(),
                )

        except Exception:
            logger.exception("Could not list upcoming events.")
            await ctx.send(
                "Etkinlikler yüklenirken bir hata oluştu."
            )


async def setup(bot: commands.Bot):
    await bot.add_cog(EventAnnouncementCog(bot))

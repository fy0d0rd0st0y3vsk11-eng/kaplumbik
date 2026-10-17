
import logging
from datetime import timezone

import discord
from discord.ext import commands

from app.database.event_models import Event
from app.events.service import list_upcoming_events


logger = logging.getLogger("kaplumbik.events")


def format_event(event: Event) -> str:
    """Format a public event announcement."""

    starts_at = event.starts_at

    if starts_at.tzinfo is None:
        starts_at = starts_at.replace(tzinfo=timezone.utc)

    timestamp = int(starts_at.timestamp())

    lines = [
        f"🎮 **{discord.utils.escape_mentions(discord.utils.escape_markdown(event.title))}**",
        f"🕹️ Oyun: {discord.utils.escape_mentions(discord.utils.escape_markdown(event.game))}",
        f"🕒 Başlangıç: <t:{timestamp}:F>",
    ]

    if event.description:
        lines.append(
            discord.utils.escape_mentions(discord.utils.escape_markdown(event.description))
        )

    if event.game_link:
        lines.append(f"🔗 Oyun bağlantısı: {discord.utils.escape_mentions(event.game_link)}")

    if event.room_code and "among us" in event.game.casefold():
        lines.append(f"🚀 Among Us oda kodu: **{discord.utils.escape_mentions(discord.utils.escape_markdown(event.room_code))}**")

    return "\n".join(lines)


class EventAnnouncementCog(commands.Cog):
    """Commands for displaying upcoming public events."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @discord.app_commands.command(name="etkinlikler", description="Yaklaşan Mahzen etkinliklerini listeler.")
    async def upcoming_events(self, interaction: discord.Interaction):
        """List upcoming scheduled public events."""
        try:
            events = list_upcoming_events(limit=10)
            if not events:
                await interaction.response.send_message("📭 Yaklaşan etkinlik bulunmuyor.")
                return

            messages = [
                f"**Etkinlik #{event.id}**\n" + format_event(event)
                + f"\nKatılım butonları: `/etkinlik etkinlik_id:{event.id}`"
                for event in events
            ]
            await interaction.response.send_message(
                messages[0],
                allowed_mentions=discord.AllowedMentions.none(),
            )
            for message in messages[1:]:
                await interaction.followup.send(
                    message,
                    allowed_mentions=discord.AllowedMentions.none(),
                )
        except Exception:
            logger.exception("Could not list upcoming events.")
            error_message = "Etkinlikler yüklenirken bir hata oluştu."
            if interaction.response.is_done():
                await interaction.followup.send(error_message, ephemeral=True)
            else:
                await interaction.response.send_message(error_message, ephemeral=True)



async def setup(bot: commands.Bot):
    await bot.add_cog(EventAnnouncementCog(bot))
    

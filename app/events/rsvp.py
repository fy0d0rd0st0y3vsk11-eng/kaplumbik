
import logging

import discord
from discord.ext import commands

from app.events.service import (
    EventNotFoundError,
    EventStateError,
    list_upcoming_events,
    set_participation,
)


logger = logging.getLogger("kaplumbik.rsvp")


class EventRSVPView(discord.ui.View):
    """Buttons for joining or declining an event."""

    def __init__(self, event_id: int):
        super().__init__(timeout=None)
        self.event_id = event_id

    async def respond(
        self,
        interaction: discord.Interaction,
        status: str,
    ):
        try:
            participation = set_participation(
                event_id=self.event_id,
                discord_id=str(interaction.user.id),
                status=status,
            )

            if status == "going":
                message = "✅ Etkinliğe katılacağını kaydettim!"
            else:
                message = "📝 Katılmayacağını kaydettim."

            await interaction.response.send_message(
                message,
                ephemeral=True,
            )

        except EventNotFoundError:
            await interaction.response.send_message(
                "Bu etkinlik bulunamadı.",
                ephemeral=True,
            )

        except EventStateError as exc:
            await interaction.response.send_message(
                str(exc),
                ephemeral=True,
            )

        except Exception:
            logger.exception("Could not save event RSVP.")
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "Yanıtın kaydedilemedi. Lütfen tekrar dene.",
                    ephemeral=True,
                )


    @discord.ui.button(
        label="Katılacağım",
        style=discord.ButtonStyle.success,
        emoji="✅",
        custom_id="kaplumbik:rsvp:going",
    )
    async def going(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        await self.respond(interaction, "going")

    @discord.ui.button(
        label="Katılmayacağım",
        style=discord.ButtonStyle.secondary,
        emoji="❌",
        custom_id="kaplumbik:rsvp:not_going",
    )
    async def not_going(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        await self.respond(interaction, "not_going")


class EventRSVPCog(commands.Cog):
    """Commands for event participation."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.command(name="etkinlik")
    async def event_details(
        self,
        ctx: commands.Context,
        event_id: int,
    ):
        """Show an event and its RSVP buttons."""

        try:
            events = list_upcoming_events(limit=100)
            event = next(
                (item for item in events if item.id == event_id),
                None,
            )

            if event is None:
                await ctx.send(
                    "Etkinlik bulunamadı veya artık yaklaşan etkinlik değil."
                )
                return

            embed = discord.Embed(
                title=event.title,
                description=event.description or "Açıklama eklenmemiş.",
                color=discord.Color.green(),
            )
            embed.add_field(
                name="Oyun",
                value=event.game,
                inline=True,
            )
            embed.add_field(
                name="Başlangıç",
                value=f"<t:{int(event.starts_at.timestamp())}:F>",
                inline=False,
            )

            if event.game_link:
                embed.add_field(
                    name="Oyun bağlantısı",
                    value=event.game_link,
                    inline=False,
                )

            await ctx.send(
                embed=embed,
                view=EventRSVPView(event.id),
                allowed_mentions=discord.AllowedMentions.none(),
            )

        except Exception:
            logger.exception("Could not display event details.")
            await ctx.send(
                "Etkinlik gösterilirken bir hata oluştu."
            )


async def setup(bot: commands.Bot):
    await bot.add_cog(EventRSVPCog(bot))
              

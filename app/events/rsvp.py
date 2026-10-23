
import logging

import discord
from app.events.green_embeds import send_green_response, send_green_followup, send_green_message, send_green_reply, edit_green_response

from discord.ext import commands

from app import create_app
from app.database import db
from app.database.event_models import Event
from app.events.feature_service import get_rsvp_summary
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
        for item in self.children:
            if isinstance(item, discord.ui.Button) and item.custom_id:
                suffix = item.custom_id.rsplit(":", 1)[-1]
                item.custom_id = f"kaplumbik:rsvp:{event_id}:{suffix}"

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

            event = db.session.get(Event, self.event_id)
            summary = get_rsvp_summary(self.event_id)
            embed = discord.Embed(
                title=event.title if event else f"Etkinlik #{self.event_id}",
                description=event.description or "Açıklama eklenmemiş." if event else "",
                color=discord.Color.green(),
            )
            if event:
                embed.add_field(name="Oyun", value=event.game, inline=True)
                embed.add_field(name="Başlangıç", value=f"<t:{int(event.starts_at.replace(tzinfo=event.starts_at.tzinfo or __import__('datetime').timezone.utc).timestamp())}:F>", inline=False)
                if event.game_link:
                    embed.add_field(name="Oyun bağlantısı", value=event.game_link, inline=False)
            def member_list(ids):
                shown = [f"<@{user_id}>" for user_id in ids[:12]]
                if len(ids) > 12:
                    shown.append(f"… ve {len(ids) - 12} kişi daha")
                return ", ".join(shown) if shown else "Henüz yanıt yok"
            embed.add_field(name=f"Katılacağım ({len(summary['going'])})", value=member_list(summary["going"]), inline=False)
            embed.add_field(name=f"Katılmayacağım ({len(summary['not_going'])})", value=member_list(summary["not_going"]), inline=False)
            await edit_green_response(interaction, embed=embed, view=self, allowed_mentions=discord.AllowedMentions.none())
            await send_green_followup(interaction, message, ephemeral=True)

        except EventNotFoundError:
            await send_green_response(interaction, 
                "Bu etkinlik bulunamadı.",
                ephemeral=True,
            )

        except EventStateError as exc:
            await send_green_response(interaction, 
                str(exc),
                ephemeral=True,
            )

        except Exception:
            logger.exception("Could not save event RSVP.")
            if not interaction.response.is_done():
                await send_green_response(interaction, 
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

    async def cog_load(self):
        # Re-register persistent event buttons after bot restarts.
        from app import create_app
        from app.database import db
        from app.database.event_models import Event
        app = create_app()
        with app.app_context():
            events = db.session.query(Event.id).all()
            event_ids = [row.id for row in events]
        for event_id in event_ids:
            self.bot.add_view(EventRSVPView(event_id))

    @discord.app_commands.command(name="etkinlik", description="Bir etkinliğin ayrıntılarını ve katılım butonlarını gösterir.")
    async def event_details(
        self,
        interaction: discord.Interaction,
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
                await send_green_response(interaction, 
                    "Etkinlik bulunamadı veya artık yaklaşan etkinlik değil.",
                    ephemeral=True,
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

            summary = get_rsvp_summary(event.id)
            embed.add_field(name=f"Katılacağım ({len(summary['going'])})", value=", ".join(f"<@{user_id}>" for user_id in summary["going"][:12]) or "Henüz yanıt yok", inline=False)
            embed.add_field(name=f"Katılmayacağım ({len(summary['not_going'])})", value=", ".join(f"<@{user_id}>" for user_id in summary["not_going"][:12]) or "Henüz yanıt yok", inline=False)
            await send_green_response(interaction, 
                embed=embed,
                view=EventRSVPView(event.id),
                allowed_mentions=discord.AllowedMentions.none(),
            )

        except Exception:
            logger.exception("Could not display event details.")
            error_message = "Etkinlik gösterilirken bir hata oluştu."
            if interaction.response.is_done():
                await send_green_followup(interaction, error_message, ephemeral=True)
            else:
                await send_green_response(interaction, error_message, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(EventRSVPCog(bot))
              

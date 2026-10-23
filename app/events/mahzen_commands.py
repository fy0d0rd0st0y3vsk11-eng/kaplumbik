"""Mahzen-only slash commands: people directory, server knowledge and giveaways."""
import logging
import secrets
from datetime import datetime, timezone

import discord
from app.events.green_embeds import send_green_response, send_green_followup, send_green_message, send_green_reply, edit_green_response

from discord import app_commands
from discord.ext import commands
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app import create_app
from app.database import db
from app.database.advanced_models import Giveaway, GiveawayParticipant, PersonProfile, MemberIntro
from app.database.models import AuditLog, UserProfile
from app.database.event_models import Event, EventParticipation
from app.events.feature_service import get_setting

logger = logging.getLogger("kaplumbik.mahzen_commands")


def _aware(value):
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _get_people(guild_id):
    app = create_app()
    with app.app_context():
        people = [{"id": f"p:{p.id}", "name": p.name, "info": p.info}
                  for p in db.session.execute(select(PersonProfile).order_by(PersonProfile.name.asc()).limit(1000)).scalars().all()]
        if guild_id is not None:
            members = db.session.execute(select(MemberIntro).where(
                MemberIntro.guild_id == str(guild_id), MemberIntro.status == "approved"
            ).order_by(MemberIntro.name.asc()).limit(1000)).scalars().all()
            people.extend({"id": f"m:{p.id}", "name": p.name, "info": p.info} for p in members)
        return sorted(people, key=lambda p: p["name"].casefold())


def _person_info(person_key, guild_id):
    try:
        kind, raw_id = str(person_key).split(":", 1)
        person_id = int(raw_id)
    except (ValueError, TypeError):
        return None
    app = create_app()
    with app.app_context():
        if kind == "p":
            person = db.session.get(PersonProfile, person_id)
        elif kind == "m":
            person = db.session.execute(select(MemberIntro).where(
                MemberIntro.id == person_id, MemberIntro.guild_id == str(guild_id),
                MemberIntro.status == "approved"
            )).scalar_one_or_none()
        else:
            return None
        return (person.name, person.info) if person else None


class MemberIntroModal(discord.ui.Modal, title="Mahzen · Kendini tanıt"):
    intro_name = discord.ui.TextInput(
        label="Tanıtımda kullanacağın isim", placeholder="İsmin veya takma adın",
        min_length=1, max_length=100,
    )
    intro_info = discord.ui.TextInput(
        label="Kendin hakkında", placeholder="Hobilerin, sevdiğin oyunlar, ilgi alanların…",
        style=discord.TextStyle.paragraph, min_length=5, max_length=1000,
    )

    async def on_submit(self, interaction: discord.Interaction):
        if interaction.guild_id is None:
            await send_green_response(interaction, "Bu komut yalnızca Mahzen sunucusunda kullanılabilir.", ephemeral=True)
            return
        name, info = str(self.intro_name.value).strip(), str(self.intro_info.value).strip()
        if not name or not info:
            await send_green_response(interaction, "İsim ve hakkında alanlarını doldurmalısın.", ephemeral=True)
            return
        app = create_app()
        try:
            with app.app_context():
                row = db.session.execute(select(MemberIntro).where(
                    MemberIntro.guild_id == str(interaction.guild_id),
                    MemberIntro.discord_id == str(interaction.user.id)
                )).scalar_one_or_none()
                action = "member_intro.submit"
                if row is None:
                    row = MemberIntro(guild_id=str(interaction.guild_id), discord_id=str(interaction.user.id),
                                      name=name, info=info, status="pending")
                    db.session.add(row)
                else:
                    row.name, row.info, row.status, row.reviewed_by = name, info, "pending", None
                    action = "member_intro.resubmit"
                db.session.flush()
                db.session.add(AuditLog(actor_discord_id=str(interaction.user.id), action=action,
                    target_type="member_intro", target_id=str(row.id),
                    details={"name": name, "status": "pending"}, success=True))
                db.session.commit()
            await send_green_response(interaction, 
                "Tanıtımın kaydedildi ve dashboard'da onay bekliyor. Onaylandıktan sonra /kisitanit listesinde görünecek. 🐢",
                ephemeral=True, allowed_mentions=discord.AllowedMentions.none())
        except Exception:
            with app.app_context():
                db.session.rollback()
            logger.exception("Member self-intro submission failed")
            if not interaction.response.is_done():
                await send_green_response(interaction, "Tanıtım kaydedilemedi. Birazdan tekrar dene.", ephemeral=True)


def _giveaway_snapshot(giveaway_id):
    app = create_app()
    with app.app_context():
        giveaway = db.session.get(Giveaway, giveaway_id)
        if giveaway is None:
            return None
        entrants = db.session.execute(
            select(GiveawayParticipant).where(
                GiveawayParticipant.giveaway_id == giveaway_id
            ).order_by(GiveawayParticipant.joined_at.asc())
        ).scalars().all()
        return {
            "id": giveaway.id,
            "title": giveaway.title,
            "prize": giveaway.prize,
            "description": giveaway.description,
            "starts_at": _aware(giveaway.starts_at),
            "status": giveaway.status,
            "winner": giveaway.winner_discord_id,
            "participants": [item.discord_id for item in entrants],
        }


class PersonSelect(discord.ui.Select):
    def __init__(self, people):
        options = [
            discord.SelectOption(label=person["name"][:100], value=person["id"],
                description=(person["info"] or "Tanıtımı görüntüle").replace("\n", " ")[:100])
            for person in people
        ]
        super().__init__(
            placeholder="Merak ettiğin kişiyi seç…",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="mahzen:person-intro-select",
        )

    async def callback(self, interaction: discord.Interaction):
        try:
            result = _person_info(self.values[0], interaction.guild_id)
            if result is None:
                await send_green_response(interaction, 
                    "Bu kişi kaydı artık bulunmuyor. Paneldeki liste yenilenmeli.",
                    ephemeral=True,
                )
                return
            name, info = result
            embed = discord.Embed(
                title=f"👋 {name} kimdir?",
                description=info[:4000],
                color=discord.Color.from_rgb(166, 143, 255),
            )
            embed.set_footer(text="Mahzen · Kişi tanıtımı")
            await send_green_response(interaction, 
                embed=embed, ephemeral=True,
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except Exception:
            logger.exception("Person intro select failed")
            if not interaction.response.is_done():
                await send_green_response(interaction, 
                    "Kişi tanıtımı yüklenemedi. Birazdan tekrar dene.",
                    ephemeral=True,
                )


class PersonPageButton(discord.ui.Button):
    def __init__(self, direction: int, disabled: bool = False):
        label = "← Önceki 25 kişi" if direction < 0 else "Sonraki 25 kişi →"
        super().__init__(
            label=label,
            style=discord.ButtonStyle.secondary,
            disabled=disabled,
            custom_id=f"mahzen:person-page:{direction}",
        )
        self.direction = direction

    async def callback(self, interaction: discord.Interaction):
        view = self.view
        if not isinstance(view, PersonSelectView):
            await interaction.response.defer()
            return
        view.page = max(0, min(view.page + self.direction, view.page_count - 1))
        view.refresh_items()
        await edit_green_response(interaction, view=view)


class PersonSelectView(discord.ui.View):
    def __init__(self, people, page: int = 0):
        super().__init__(timeout=120)
        self.people = list(people)
        self.page_count = max(1, (len(self.people) + 24) // 25)
        self.page = max(0, min(page, self.page_count - 1))
        self.refresh_items()

    def refresh_items(self):
        self.clear_items()
        page_people = self.people[self.page * 25:(self.page + 1) * 25]
        self.add_item(PersonSelect(page_people))
        if self.page_count > 1:
            self.add_item(PersonPageButton(-1, disabled=self.page == 0))
            self.add_item(PersonPageButton(1, disabled=self.page >= self.page_count - 1))


class MahzenCommands(commands.Cog):
    """Commands for the Mahzen community, not generic server advertising."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="kendinitanit", description="İsim ve hakkında bilgilerini girerek tanıtımını onaya gönder.")
    async def self_intro(self, interaction: discord.Interaction):
        if interaction.guild_id is None:
            await send_green_response(interaction, "Bu komut yalnızca Mahzen sunucusunda kullanılabilir.", ephemeral=True)
            return
        await interaction.response.send_modal(MemberIntroModal())

    @app_commands.command(name="kisitanit", description="Onaylanmış üyeler arasından birini seçip tanıtımını oku.")
    async def person_directory(self, interaction: discord.Interaction):
        people = _get_people(interaction.guild_id)
        if not people:
            await send_green_response(interaction, 
                "Henüz kişi tanıtımı eklenmemiş. Yönetim panelindeki Kişi tanıtımları bölümünden eklenebilir.",
                ephemeral=True,
            )
            return
        await send_green_response(interaction, 
            "Kimi merak ettin? Aşağıdaki listeden birini seç. 🐢",
            view=PersonSelectView(people),
            ephemeral=True,
        )

    @app_commands.command(name="cekilisler", description="Mahzen'deki açık çekilişleri ve ödüllerini listele.")
    async def giveaways(self, interaction: discord.Interaction):
        app = create_app()
        with app.app_context():
            rows = db.session.execute(
                select(Giveaway).where(Giveaway.status == "open").order_by(Giveaway.starts_at.asc()).limit(10)
            ).scalars().all()
            items = [
                f"**#{row.id} · {discord.utils.escape_markdown(row.title)}**\n"
                f"🎁 Ödül: {discord.utils.escape_markdown(row.prize)}\n"
                f"🕒 Çekiliş zamanı: <t:{int(_aware(row.starts_at).timestamp())}:F>\n"
                f"👥 Katılımcı: {len(row.participants)} · Katılmak için /cekiliskatil cekilis_id:{row.id}"
                for row in rows
            ]
        if not items:
            await send_green_response(interaction, "Şu an açık çekiliş yok. Yeni çekilişler panelden eklenir. 🎁")
            return
        await send_green_response(interaction, 
            "\n\n".join(items)[:1900],
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @app_commands.command(name="cekilisbilgi", description="Bir Mahzen çekilişinin ödülünü, saatini ve durumunu göster.")
    async def giveaway_info(self, interaction: discord.Interaction, cekilis_id: int):
        data = _giveaway_snapshot(cekilis_id)
        if not data:
            await send_green_response(interaction, "Bu numarayla bir çekiliş bulamadım.", ephemeral=True)
            return
        when = f"<t:{int(data['starts_at'].timestamp())}:F>" if data["starts_at"] else "Belirtilmemiş"
        winner = f"<@{data['winner']}>" if data["winner"] else "Henüz belirlenmedi"
        embed = discord.Embed(
            title=f"🎁 Çekiliş #{data['id']} · {data['title'][:200]}",
            description=data["description"] or "Ek açıklama yok.",
            color=discord.Color.from_rgb(158, 231, 215),
        )
        embed.add_field(name="Ödül", value=data["prize"][:1024], inline=False)
        embed.add_field(name="Çekiliş zamanı", value=when, inline=False)
        embed.add_field(name="Durum", value=data["status"], inline=True)
        embed.add_field(name="Katılımcı sayısı", value=str(len(data["participants"])), inline=True)
        embed.add_field(name="Kazanan", value=winner, inline=False)
        await send_green_response(interaction, embed=embed, allowed_mentions=discord.AllowedMentions.none())

    @app_commands.command(name="cekiliskatil", description="Puan şartını karşılıyorsan açık Mahzen çekilişine katıl.")
    async def giveaway_join(self, interaction: discord.Interaction, cekilis_id: int):
        app = create_app()
        try:
            with app.app_context():
                giveaway = db.session.execute(select(Giveaway).where(Giveaway.id == cekilis_id).with_for_update()).scalar_one_or_none()
                if giveaway is None:
                    await send_green_response(interaction, "Bu çekilişi bulamadım.", ephemeral=True)
                    return
                if giveaway.status != "open":
                    await send_green_response(interaction, "Bu çekiliş artık katılıma açık değil.", ephemeral=True)
                    return
                starts_at = _aware(giveaway.starts_at)
                if starts_at and datetime.now(timezone.utc) >= starts_at:
                    await send_green_response(interaction, "Katılım saati dolmuş. Yönetici çekilişi sonuçlandırabilir.", ephemeral=True)
                    return
                minimum = int(get_setting("giveaway_min_points", "100") or "100")
                profile = db.session.execute(
                    select(UserProfile).where(UserProfile.discord_id == str(interaction.user.id))
                ).scalar_one_or_none()
                balance = profile.balance if profile else 0
                if balance < minimum:
                    await send_green_response(interaction, 
                        f"Bu çekilişe katılmak için en az {minimum} Mahzen puanı gerekiyor. Mevcut bakiyen: {balance}.",
                        ephemeral=True,
                    )
                    return
                exists = db.session.execute(
                    select(GiveawayParticipant.id).where(
                        GiveawayParticipant.giveaway_id == giveaway.id,
                        GiveawayParticipant.discord_id == str(interaction.user.id),
                    )
                ).scalar_one_or_none()
                if exists:
                    await send_green_response(interaction, "Zaten katılmışsın! İkinci bir bilet yazmıyorum. 🐢", ephemeral=True)
                    return
                db.session.add(GiveawayParticipant(
                    giveaway_id=giveaway.id,
                    discord_id=str(interaction.user.id),
                ))
                db.session.commit()
                title = giveaway.title
                prize = giveaway.prize
            await send_green_response(interaction, 
                f"🎟️ {title} çekilişine katıldın! Ödül: {prize}. Bol şans!",
                ephemeral=True,
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except IntegrityError:
            with app.app_context():
                db.session.rollback()
            if not interaction.response.is_done():
                await send_green_response(interaction, "Zaten katılmış görünüyorsun.", ephemeral=True)
        except Exception:
            with app.app_context():
                db.session.rollback()
            logger.exception("Could not join giveaway")
            if not interaction.response.is_done():
                await send_green_response(interaction, "Çekilişe katılım kaydedilemedi. Birazdan tekrar dene.", ephemeral=True)

    @app_commands.command(name="cekiliskatilimlar", description="Bir çekilişin katılımcılarını yönetici olarak gör.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def giveaway_participants(self, interaction: discord.Interaction, cekilis_id: int):
        data = _giveaway_snapshot(cekilis_id)
        if not data:
            await send_green_response(interaction, "Bu çekilişi bulamadım.", ephemeral=True)
            return
        if not data["participants"]:
            await send_green_response(interaction, f"#{cekilis_id} çekilişine henüz kimse katılmamış.", ephemeral=True)
            return
        lines = [f"• <@{user_id}> — {user_id}" for user_id in data["participants"]]
        await send_green_response(interaction, 
            f"#{cekilis_id} · {data['title']} — {len(lines)} katılımcı\n" + "\n".join(lines)[:1700],
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @app_commands.command(name="cekiliskazanan", description="Bir Mahzen çekilişinin kaydedilmiş kazananını göster.")
    async def giveaway_winner(self, interaction: discord.Interaction, cekilis_id: int):
        data = _giveaway_snapshot(cekilis_id)
        if not data:
            await send_green_response(interaction, "Bu çekilişi bulamadım.", ephemeral=True)
        elif data["winner"]:
            await send_green_response(interaction, 
                f"🎉 #{cekilis_id} · {data['title']} kazananı: <@{data['winner']}>",
                allowed_mentions=discord.AllowedMentions.none(),
            )
        else:
            await send_green_response(interaction, 
                f"#{cekilis_id} · {data['title']} için henüz kazanan belirlenmedi.",
                ephemeral=True,
            )

    @app_commands.command(name="cekilisbitir", description="Katılımcılar arasından rastgele kazanan seçip çekilişi bitir.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def giveaway_finish(self, interaction: discord.Interaction, cekilis_id: int):
        app = create_app()
        try:
            with app.app_context():
                giveaway = db.session.execute(select(Giveaway).where(Giveaway.id == cekilis_id).with_for_update()).scalar_one_or_none()
                if giveaway is None:
                    await send_green_response(interaction, "Bu çekilişi bulamadım.", ephemeral=True)
                    return
                if giveaway.status != "open":
                    await send_green_response(interaction, "Bu çekiliş zaten kapatılmış.", ephemeral=True)
                    return
                starts_at = _aware(giveaway.starts_at)
                if starts_at and datetime.now(timezone.utc) < starts_at:
                    await send_green_response(interaction, "Çekiliş zamanı henüz gelmedi; zamanı gelince tekrar dene.", ephemeral=True)
                    return
                entrants = db.session.execute(
                    select(GiveawayParticipant).where(GiveawayParticipant.giveaway_id == giveaway.id)
                ).scalars().all()
                if not entrants:
                    await send_green_response(interaction, "Katılımcı yok; kazanan seçilmedi.", ephemeral=True)
                    return
                winner = secrets.choice(entrants)
                giveaway.winner_discord_id = winner.discord_id
                giveaway.status = "ended"
                giveaway.ended_at = datetime.now(timezone.utc)
                title, prize, winner_id = giveaway.title, giveaway.prize, winner.discord_id
                db.session.add(AuditLog(
                    actor_discord_id=str(interaction.user.id),
                    action="giveaway.end",
                    target_type="giveaway",
                    target_id=str(giveaway.id),
                    details={
                        "winner_discord_id": winner_id,
                        "participant_count": len(entrants),
                        "source": "discord_command",
                    },
                    success=True,
                ))
                db.session.commit()
            await send_green_response(interaction, 
                f"🎉 {title} çekilişi tamamlandı! Ödül: {prize} · Kazanan: <@{winner_id}>",
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except Exception:
            with app.app_context():
                db.session.rollback()
            logger.exception("Could not finish giveaway")
            if not interaction.response.is_done():
                await send_green_response(interaction, "Çekiliş bitirilemedi. Paneldeki işlem kayıtlarını kontrol et.", ephemeral=True)

    @app_commands.command(name="mahzenbilgi", description="Yönetim paneline kaydedilen Mahzen bilgilerini göster.")
    async def server_knowledge(self, interaction: discord.Interaction):
        app = create_app()
        with app.app_context():
            info = (get_setting("server_knowledge", "") or "").strip()
            games = []
            for key, label in (
                ("minecraft_realms_link", "Minecraft Realms"),
                ("gartic_phone_link", "Gartic Phone"),
                ("among_us_room_code", "Among Us oda kodu"),
            ):
                value = (get_setting(key, "") or "").strip()
                if value:
                    games.append(f"**{label}:** {discord.utils.escape_mentions(value)}")
        sections = [info[:3000]] if info else ["Mahzen hakkında henüz panelden bilgi girilmemiş."]
        sections.extend(games)
        content = "\n\n".join(sections)
        chunks = [content[index:index + 1900] for index in range(0, len(content), 1900)] or ["Mahzen bilgisi henüz boş."]
        await send_green_response(interaction, 
            chunks[0],
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none(),
        )
        for chunk in chunks[1:]:
            await send_green_followup(interaction, 
                chunk,
                ephemeral=True,
                allowed_mentions=discord.AllowedMentions.none(),
            )

    @app_commands.command(name="oyunlar", description="Mahzen'de ayarlanmış oyun bağlantılarını ve oda bilgilerini göster.")
    async def game_links(self, interaction: discord.Interaction):
        app = create_app()
        with app.app_context():
            rows = [
                ("Minecraft Realms", get_setting("minecraft_realms_link", "")),
                ("Gartic Phone", get_setting("gartic_phone_link", "")),
                ("Among Us oda kodu", get_setting("among_us_room_code", "")),
            ]
        lines = [f"**{label}:** {discord.utils.escape_mentions(value)}" for label, value in rows if (value or "").strip()]
        await send_green_response(interaction, 
            "\n".join(lines) if lines else "Oyun bağlantıları henüz dashboard'a eklenmemiş.",
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @app_commands.command(name="etkinlikbilgi", description="Bir Mahzen etkinliğinin saatini, oyununu ve katılım sayılarını göster.")
    async def event_info(self, interaction: discord.Interaction, etkinlik_id: int):
        app = create_app()
        with app.app_context():
            event = db.session.get(Event, etkinlik_id)
            if event is None:
                data = None
            else:
                rows = db.session.execute(
                    select(EventParticipation).where(EventParticipation.event_id == event.id)
                ).scalars().all()
                data = {
                    "id": event.id,
                    "title": event.title,
                    "game": event.game,
                    "description": event.description or "",
                    "starts_at": _aware(event.starts_at),
                    "status": event.status,
                    "going": sum(row.status == "going" for row in rows),
                    "not_going": sum(row.status == "not_going" for row in rows),
                    "attended": sum(row.status == "attended" for row in rows),
                }
        if data is None:
            await send_green_response(interaction, "Bu etkinliği bulamadım.", ephemeral=True)
            return
        when = f"<t:{int(data['starts_at'].timestamp())}:F>" if data["starts_at"] else "Belirtilmemiş"
        embed = discord.Embed(
            title=f"🎮 Etkinlik #{data['id']} · {data['title'][:200]}",
            description=data["description"][:3000] or "Ek açıklama yok.",
            color=discord.Color.from_rgb(166, 143, 255),
        )
        embed.add_field(name="Oyun", value=data["game"][:200], inline=True)
        embed.add_field(name="Başlangıç", value=when, inline=False)
        embed.add_field(name="Durum", value=data["status"], inline=True)
        embed.add_field(name="Katılacağım", value=str(data["going"]), inline=True)
        embed.add_field(name="Katılmayacağım", value=str(data["not_going"]), inline=True)
        embed.add_field(name="Katıldığı onaylandı", value=str(data["attended"]), inline=True)
        await send_green_response(interaction, embed=embed, allowed_mentions=discord.AllowedMentions.none())

    @app_commands.command(name="cekilisarsiv", description="Sonuçlanmış Mahzen çekilişlerini ve kazananlarını göster.")
    async def giveaway_archive(self, interaction: discord.Interaction):
        app = create_app()
        with app.app_context():
            rows = db.session.execute(
                select(Giveaway).where(Giveaway.status == "ended").order_by(Giveaway.ended_at.desc()).limit(10)
            ).scalars().all()
            lines = [
                f"**#{row.id} · {discord.utils.escape_markdown(row.title)}** — ödül: {discord.utils.escape_markdown(row.prize)} — kazanan: <@{row.winner_discord_id}>"
                for row in rows
            ]
        await send_green_response(interaction, 
            "\n".join(lines)[:1900] if lines else "Henüz sonuçlanmış çekiliş yok.",
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @app_commands.command(name="mahzenkomutlar", description="Kaplumbik'in Mahzen'e özel komutlarını göster.")
    async def mahzen_commands(self, interaction: discord.Interaction):
        await send_green_response(interaction, 
            "**Mahzen komutları**\n"
            "• /kendinitanit — tanıtımını yazıp onaya gönder\n"
            "• /kisitanit — onaylı kişi tanıtımlarını listeden seçip oku\n"
            "• /kimtasarladi — Kaplumbik'in tasarımcısını göster\n"
            "• /mahzenbilgi — kayıtlı Mahzen bilgileri\n"
            "• /oyunlar — kayıtlı oyun bağlantıları\n"
            "• /etkinlikler — yaklaşan etkinlikler\n"
            "• /etkinlik — bir etkinliğin katılım butonlarını aç\n"
            "• /etkinlikbilgi — etkinlik saati ve katılım sayıları\n"
            "• /etkinlikgecmisi — etkinlik katılım geçmişi\n"
            "• /profil — puan ve profil bilgileri\n"
            "• /cekilisler — açık çekilişler\n"
            "• /cekilisarsiv — sonuçlanan çekilişler ve kazananlar\n"
            "• /cekilisbilgi — çekiliş detayları\n"
            "• /cekiliskatil — puan şartını karşılıyorsan katıl\n"
            "• /cekiliskatilimlar — katılımcı listesi (yönetici)\n"
            "• /cekiliskazanan — kazananı göster\n"
            "• /cekilisbitir — çekilişi bitir (yönetici)",
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none(),
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(MahzenCommands(bot))

import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
from app import create_app
from app.core.config import settings
from app.database import db
from app.database.community_models import MemberGameProfile, CommunityPoll, CommunityPollVote, CommunitySuggestion, CommunitySuggestionVote, WeeklyQuest, WeeklyQuestProgress, RewardShopItem, MemberCollectionItem, FeaturePermission
from app.database.models import AuditLog, EconomyTransaction, UserProfile
from app.events.feature_service import get_setting

log = logging.getLogger("kaplumbik.community")
TR = ZoneInfo("Europe/Istanbul")

def utcnow():
    return datetime.now(timezone.utc)

def is_owner(i):
    return bool(settings.owner_discord_id) and str(i.user.id) == str(settings.owner_discord_id)

def is_admin(i):
    return is_owner(i) or (isinstance(i.user, discord.Member) and i.user.guild_permissions.administrator)

def seed_quests():
    now = datetime.now(TR)
    monday = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    start, end = monday.astimezone(timezone.utc), (monday + timedelta(days=7)).astimezone(timezone.utc)
    data = [
        (f"{monday.date()}_messages", "Sohbeti Canlandır", "Bu hafta 10 mesaj gönder.", "messages", 10, 20),
        (f"{monday.date()}_days", "Mahzen'e Uğra", "Bu hafta 3 ayrı günde sohbete katıl.", "active_days", 3, 35),
        (f"{monday.date()}_shared", "Mahzen Birlikte", "Ortak görev: 5 farklı üye katkı versin.", "shared_members", 5, 15),
    ]
    for key,title,desc,kind,target,reward in data:
        if db.session.execute(select(WeeklyQuest.id).where(WeeklyQuest.key == key)).scalar_one_or_none() is None:
            db.session.add(WeeklyQuest(key=key,title=title,description=desc,quest_type=kind,target=target,reward_points=reward,starts_at=start,ends_at=end,enabled=True))
    db.session.commit()

class PollView(discord.ui.View):
    def __init__(self, poll_id, options):
        super().__init__(timeout=None)
        self.poll_id = poll_id
        for idx, option in enumerate(options[:5]):
            button = discord.ui.Button(label=option[:80], style=discord.ButtonStyle.primary, custom_id=f"kaplumbik:poll:{poll_id}:{idx}")
            button.callback = self.make_callback(idx)
            self.add_item(button)
    def make_callback(self, idx):
        async def callback(interaction):
            app=create_app()
            with app.app_context():
                poll=db.session.get(CommunityPoll,self.poll_id)
                if not poll or poll.status != "open" or (poll.ends_at and poll.ends_at <= utcnow()):
                    await interaction.response.send_message("Bu anket artık açık değil.",ephemeral=True); return
                vote=db.session.execute(select(CommunityPollVote).where(CommunityPollVote.poll_id==poll.id,CommunityPollVote.discord_id==str(interaction.user.id))).scalar_one_or_none()
                if vote: vote.option_index=idx
                else: db.session.add(CommunityPollVote(poll_id=poll.id,discord_id=str(interaction.user.id),option_index=idx))
                db.session.commit()
            await interaction.response.send_message("Oyun kaydedildi. Tekrar oy vererek seçimini değiştirebilirsin.",ephemeral=True)
        return callback

class MahzenCommunity(commands.Cog):
    def __init__(self, bot): self.bot=bot

    @app_commands.command(name="oyunprofil", description="Oyun arkadaşlığı için profilini oluştur veya güncelle.")
    async def game_profile(self, interaction: discord.Interaction, oyunlar: str, platform: str, uygunluk: str, ses: str="either", tarz: str="", gorunur: bool=True):
        games=list(dict.fromkeys(x.strip()[:50] for x in oyunlar.split(",") if x.strip()))[:12]
        if not games or len(platform)>100 or len(uygunluk)>200 or len(tarz)>100 or ses.casefold() not in {"yes","no","either","evet","hayır","hayir","farketmez"}:
            await interaction.response.send_message("Oyunlar, platform, uygunluk veya ses tercihi geçersiz.",ephemeral=True); return
        voice={"evet":"yes","hayır":"no","hayir":"no","farketmez":"either"}.get(ses.casefold(),ses.casefold())
        app=create_app()
        with app.app_context():
            row=db.session.execute(select(MemberGameProfile).where(MemberGameProfile.discord_id==str(interaction.user.id))).scalar_one_or_none()
            if not row: row=MemberGameProfile(discord_id=str(interaction.user.id)); db.session.add(row)
            row.games,row.platform,row.availability,row.voice,row.style,row.visible=games,platform.strip(),uygunluk.strip(),voice,tarz.strip(),gorunur
            db.session.commit()
        await interaction.response.send_message("Oyun profilin kaydedildi. Görünürlüğü kapatmak için komutu gorunur=false ile güncelle.",ephemeral=True)

    @app_commands.command(name="oyunarkadasi", description="Bir oyuna uygun oyun arkadaşlarını bul.")
    async def find_buddy(self, interaction: discord.Interaction, oyun: str):
        app=create_app()
        with app.app_context():
            rows=db.session.execute(select(MemberGameProfile).where(MemberGameProfile.visible.is_(True),MemberGameProfile.discord_id!=str(interaction.user.id))).scalars().all()
            own=db.session.execute(select(MemberGameProfile).where(MemberGameProfile.discord_id==str(interaction.user.id))).scalar_one_or_none()
            matches=[]
            for row in rows:
                if any(oyun.casefold() in g.casefold() for g in (row.games or [])):
                    score=int(bool(own and own.platform.casefold()==row.platform.casefold()))+int(bool(own and own.voice==row.voice))
                    matches.append((score,row.discord_id,row.platform,row.availability,row.voice,row.style))
            matches.sort(reverse=True)
        if not matches:
            await interaction.response.send_message(f"{oyun} için görünür profil bulamadım. Üyeler oyun profili ekleyebilir.",ephemeral=True); return
        lines=[f"<@{uid}> · {platform or 'Platform yok'} · {avail or 'Uygunluk yok'} · ses: {voice} · {style}" for _,uid,platform,avail,voice,style in matches[:10]]
        await interaction.response.send_message("Oyun arkadaşları\n"+"\n".join(lines),ephemeral=True,allowed_mentions=discord.AllowedMentions.none())

    @app_commands.command(name="anket", description="2–5 seçenekli anket oluştur.")
    async def create_poll(self, interaction: discord.Interaction, soru: str, secenekler: str, sure_saat: app_commands.Range[int,1,168]=24, anonim: bool=False):
        options=list(dict.fromkeys(x.strip() for x in secenekler.split("|") if x.strip()))
        if not 5<=len(soru)<=300 or not 2<=len(options)<=5 or any(len(x)>80 for x in options):
            await interaction.response.send_message("Soru 5–300 karakter; 2–5 seçenek, her biri en fazla 80 karakter olmalı. Seçenekleri | ile ayır.",ephemeral=True); return
        await interaction.response.defer(thinking=True)
        app=create_app()
        with app.app_context():
            poll=CommunityPoll(guild_id=str(interaction.guild_id or "dm"),channel_id=str(interaction.channel_id),creator_id=str(interaction.user.id),question=soru,options=options,anonymous=anonim,ends_at=utcnow()+timedelta(hours=int(sure_saat)))
            db.session.add(poll); db.session.commit(); poll_id=poll.id
        embed=discord.Embed(title="Anket: "+soru,description="Bir seçeneğe tıkla. Oyunu değiştirmen mümkün.",color=discord.Color.from_rgb(146,166,132))
        try:
            msg=await interaction.channel.send(embed=embed,view=PollView(poll_id,options))
            with app.app_context():
                row=db.session.get(CommunityPoll,poll_id); row.message_id=str(msg.id); db.session.commit()
            await interaction.followup.send(f"Anket oluşturuldu: #{poll_id}",ephemeral=True)
        except discord.HTTPException:
            with app.app_context():
                row=db.session.get(CommunityPoll,poll_id); row.status="failed"; db.session.commit()
            await interaction.followup.send("Anket mesajı gönderilemedi. Botun kanal izinlerini kontrol edin.",ephemeral=True)

    @app_commands.command(name="onerigonder", description="Anonim veya isimli öneri gönder.")
    async def suggestion_submit(self, interaction: discord.Interaction, metin: app_commands.Range[str,10,1500], anonim: bool=False):
        if not interaction.guild_id:
            await interaction.response.send_message("Öneriler yalnızca sunucuda gönderilebilir.",ephemeral=True); return
        app=create_app()
        with app.app_context():
            recent=db.session.execute(select(CommunitySuggestion.id).where(CommunitySuggestion.creator_id==str(interaction.user.id),CommunitySuggestion.created_at>=utcnow()-timedelta(minutes=30)).limit(1)).scalar_one_or_none()
            if recent:
                await interaction.response.send_message("Yeni öneri için 30 dakika beklemelisin.",ephemeral=True); return
            row=CommunitySuggestion(guild_id=str(interaction.guild_id),creator_id=str(interaction.user.id),anonymous=anonim,content=metin.strip())
            db.session.add(row); db.session.commit(); sid=row.id
            channel_id=get_setting("suggestion_channel_id","")
        channel=None
        if channel_id.isdigit():
            channel=self.bot.get_channel(int(channel_id))
            if channel is None:
                try: channel=await self.bot.fetch_channel(int(channel_id))
                except discord.HTTPException: channel=None
        channel=channel or interaction.channel
        embed=discord.Embed(title=f"Mahzen önerisi #{sid}",description=metin.strip()[:4000],color=discord.Color.from_rgb(146,166,132))
        embed.add_field(name="Gönderen",value="Anonim üye" if anonim else interaction.user.mention,inline=True)
        embed.add_field(name="Durum",value="Beklemede",inline=True)
        try:
            msg=await channel.send(embed=embed,allowed_mentions=discord.AllowedMentions.none())
            with app.app_context():
                fresh=db.session.get(CommunitySuggestion,sid); fresh.message_id=str(msg.id); db.session.commit()
            await interaction.response.send_message(f"Önerin #{sid} gönderildi.",ephemeral=True)
        except discord.HTTPException:
            await interaction.response.send_message("Öneri kaydedildi ama mesajı gönderemedim; yönetici kanal izinlerini kontrol etmeli.",ephemeral=True)

    @app_commands.command(name="onerioyla", description="Bir öneriye oy ver (1 destek, -1 karşı).")
    async def suggestion_vote(self, interaction: discord.Interaction, onerino: int, oy: app_commands.Range[int,-1,1]):
        if oy==0:
            await interaction.response.send_message("Oy 1 veya -1 olmalı.",ephemeral=True); return
        app=create_app()
        with app.app_context():
            row=db.session.get(CommunitySuggestion,onerino)
            if not row or row.status in {"rejected","implemented"}:
                await interaction.response.send_message("Öneri bulunamadı veya oylamaya kapalı.",ephemeral=True); return
            vote=db.session.execute(select(CommunitySuggestionVote).where(CommunitySuggestionVote.suggestion_id==onerino,CommunitySuggestionVote.discord_id==str(interaction.user.id))).scalar_one_or_none()
            if vote: vote.value=oy
            else: db.session.add(CommunitySuggestionVote(suggestion_id=onerino,discord_id=str(interaction.user.id),value=oy))
            db.session.commit()
            total=db.session.scalar(select(func.coalesce(func.sum(CommunitySuggestionVote.value),0)).where(CommunitySuggestionVote.suggestion_id==onerino))
        await interaction.response.send_message(f"Öneri #{onerino} için oy kaydedildi. Net oy: {total}.",ephemeral=True)

    @app_commands.command(name="oneridurum", description="Öneri durumunu yönetici olarak güncelle.")
    @app_commands.choices(durum=[app_commands.Choice(name="İnceleniyor",value="reviewing"),app_commands.Choice(name="Kabul edildi",value="accepted"),app_commands.Choice(name="Reddedildi",value="rejected"),app_commands.Choice(name="Uygulandı",value="implemented")])
    async def suggestion_status(self, interaction: discord.Interaction, onerino: int, durum: app_commands.Choice[str]):
        if not is_admin(interaction):
            await interaction.response.send_message("Yönetici yetkisi gerekiyor.",ephemeral=True); return
        app=create_app()
        with app.app_context():
            row=db.session.get(CommunitySuggestion,onerino)
            if not row: await interaction.response.send_message("Öneri bulunamadı.",ephemeral=True); return
            row.status=durum.value
            db.session.add(AuditLog(actor_discord_id=str(interaction.user.id),action="suggestion.status",target_type="suggestion",target_id=str(onerino),details={"status":durum.value},success=True)); db.session.commit()
        await interaction.response.send_message(f"Öneri #{onerino} durumu: {durum.name}.",ephemeral=True)

    @app_commands.command(name="gorevler", description="Bu haftanın kişisel ve ortak görevlerini göster.")
    async def quests(self, interaction: discord.Interaction):
        app=create_app()
        with app.app_context():
            seed_quests()
            quests=db.session.execute(select(WeeklyQuest).where(WeeklyQuest.enabled.is_(True),WeeklyQuest.starts_at<=utcnow(),WeeklyQuest.ends_at>utcnow()).order_by(WeeklyQuest.id)).scalars().all()
            lines=[]
            for q in quests:
                p=db.session.execute(select(WeeklyQuestProgress).where(WeeklyQuestProgress.quest_id==q.id,WeeklyQuestProgress.discord_id==str(interaction.user.id))).scalar_one_or_none()
                if q.quest_type=="shared_members":
                    progress=db.session.scalar(select(func.count(WeeklyQuestProgress.id)).where(WeeklyQuestProgress.quest_id==q.id,WeeklyQuestProgress.progress>0)) or 0
                    current=f"{progress}/{q.target} farklı üye"
                else: current=f"{p.progress if p else 0}/{q.target}"
                lines.append(f"{q.title} — {q.description}\nİlerleme: {current} · ödül: {q.reward_points} puan")
        await interaction.response.send_message("Haftalık görevler\n"+"\n\n".join(lines),ephemeral=True)

    @app_commands.command(name="dukkan", description="Ödül mağazasını görüntüle.")
    async def shop(self, interaction: discord.Interaction):
        app=create_app()
        with app.app_context():
            items=db.session.execute(select(RewardShopItem).where(RewardShopItem.enabled.is_(True)).order_by(RewardShopItem.price).limit(20)).scalars().all()
        if not items:
            await interaction.response.send_message("Mağaza henüz kurulmamış. Yönetim panelinden ürün eklenmesi gerekiyor.",ephemeral=True); return
        await interaction.response.send_message("Mahzen mağazası\n"+"\n\n".join(f"{x.key} — {x.title}: {x.price} puan ({x.description or 'Açıklama yok'})" for x in items),ephemeral=True)

    @app_commands.command(name="koleksiyon", description="Koleksiyon öğelerini görüntüle.")
    async def collection(self, interaction: discord.Interaction):
        app=create_app()
        with app.app_context():
            rows=db.session.execute(select(MemberCollectionItem).where(MemberCollectionItem.discord_id==str(interaction.user.id)).order_by(MemberCollectionItem.acquired_at.desc()).limit(50)).scalars().all()
            lines=[f"{x.item_key} · {x.source}"+(f" · bitiş {x.expires_at.astimezone(TR).strftime('%d.%m.%Y')}" if x.expires_at else " · kalıcı") for x in rows if not x.expires_at or x.expires_at>utcnow()]
        await interaction.response.send_message("Koleksiyonun\n"+("\n".join(lines) if lines else "Henüz koleksiyon öğen yok."),ephemeral=True)

    @app_commands.command(name="modulizin", description="Bir modülde rol bazlı yönetim izni ayarla (yalnızca sahip).")
    async def module_permission(self, interaction: discord.Interaction, modul: str, rol: discord.Role, yonetebilir: bool):
        if not is_owner(interaction):
            await interaction.response.send_message("Modül izinlerini yalnızca sunucu sahibi değiştirebilir.",ephemeral=True); return
        if modul not in {"events","economy","suggestions","polls","profiles","security","ai","dashboard","streak"}:
            await interaction.response.send_message("Modül anahtarı geçersiz.",ephemeral=True); return
        app=create_app()
        with app.app_context():
            row=db.session.execute(select(FeaturePermission).where(FeaturePermission.module_key==modul,FeaturePermission.discord_role_id==str(rol.id))).scalar_one_or_none()
            if not row: row=FeaturePermission(module_key=modul,discord_role_id=str(rol.id)); db.session.add(row)
            row.can_manage=yonetebilir; row.updated_by=str(interaction.user.id)
            db.session.add(AuditLog(actor_discord_id=str(interaction.user.id),action="permissions.module_role",target_type="module",target_id=modul,details={"role_id":str(rol.id),"can_manage":yonetebilir},success=True)); db.session.commit()
        await interaction.response.send_message(f"{rol.name} rolünün {modul} izni güncellendi. Discord'un yerleşik izinleri yine geçerlidir.",ephemeral=True)

    @commands.Cog.listener()
    async def on_message(self, message):
        if not message.guild or message.author.bot or message.webhook_id: return
        app=create_app()
        with app.app_context():
            now=utcnow()
            quests=db.session.execute(select(WeeklyQuest).where(WeeklyQuest.enabled.is_(True),WeeklyQuest.starts_at<=now,WeeklyQuest.ends_at>now,WeeklyQuest.quest_type=="messages")).scalars().all()
            for q in quests:
                p=db.session.execute(select(WeeklyQuestProgress).where(WeeklyQuestProgress.quest_id==q.id,WeeklyQuestProgress.discord_id==str(message.author.id))).scalar_one_or_none()
                if not p: p=WeeklyQuestProgress(quest_id=q.id,discord_id=str(message.author.id),progress=0); db.session.add(p)
                p.progress=min(q.target,p.progress+1)
            shared=db.session.execute(select(WeeklyQuest).where(WeeklyQuest.enabled.is_(True),WeeklyQuest.starts_at<=now,WeeklyQuest.ends_at>now,WeeklyQuest.quest_type=="shared_members")).scalars().all()
            for q in shared:
                p=db.session.execute(select(WeeklyQuestProgress).where(WeeklyQuestProgress.quest_id==q.id,WeeklyQuestProgress.discord_id==str(message.author.id))).scalar_one_or_none()
                if not p: db.session.add(WeeklyQuestProgress(quest_id=q.id,discord_id=str(message.author.id),progress=1))
            db.session.commit()

async def setup(bot):
    await bot.add_cog(MahzenCommunity(bot))

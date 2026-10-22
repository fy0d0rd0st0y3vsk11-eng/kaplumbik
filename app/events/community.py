import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import select, func, update
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


    async def cog_load(self):
        app=create_app()
        with app.app_context():
            polls=db.session.execute(select(CommunityPoll).where(CommunityPoll.status=="open")).scalars().all()
            active=[(p.id,list(p.options),p.message_id) for p in polls]
        for poll_id,options,message_id in active:
            try:
                self.bot.add_view(PollView(poll_id,options), message_id=int(message_id) if message_id else None)
            except (ValueError, discord.HTTPException):
                log.exception("Could not restore persistent poll view %s",poll_id)

    @app_commands.command(name="goreval", description="Tamamladığın haftalık görevin puanını al.")
    async def claim_quest(self, interaction: discord.Interaction, gorev: int):
        app=create_app()
        try:
            with app.app_context():
                quest=db.session.get(WeeklyQuest,gorev)
                if not quest or not quest.enabled or quest.ends_at<=utcnow():
                    await interaction.response.send_message("Görev bulunamadı veya süresi bitti.",ephemeral=True); return
                progress=db.session.execute(select(WeeklyQuestProgress).where(WeeklyQuestProgress.quest_id==quest.id,WeeklyQuestProgress.discord_id==str(interaction.user.id))).scalar_one_or_none()
                if quest.quest_type=="shared_members":
                    total=db.session.scalar(select(func.count(WeeklyQuestProgress.id)).where(WeeklyQuestProgress.quest_id==quest.id,WeeklyQuestProgress.progress>0)) or 0
                    completed=total>=quest.target and progress is not None and progress.progress>0
                else:
                    completed=progress is not None and progress.progress>=quest.target
                if not completed:
                    await interaction.response.send_message("Görev henüz tamamlanmadı.",ephemeral=True); return
                if progress.claimed_at:
                    await interaction.response.send_message("Bu görevin ödülünü zaten aldın.",ephemeral=True); return
                if db.session.execute(select(UserProfile.id).where(UserProfile.discord_id==str(interaction.user.id))).scalar_one_or_none() is None:
                    db.session.add(UserProfile(discord_id=str(interaction.user.id),balance=0)); db.session.commit()
                adjust_balance(str(interaction.user.id),int(quest.reward_points),"weekly_quest",f"Haftalık görev: {quest.title}",actor_discord_id="kaplumbik",idempotency_key=f"quest:{quest.id}:{interaction.user.id}")
                progress.claimed_at=utcnow()
                db.session.add(AuditLog(actor_discord_id=str(interaction.user.id),action="quest.reward_claimed",target_type="quest",target_id=str(quest.id),details={"reward":quest.reward_points},success=True))
                db.session.commit()
            await interaction.response.send_message(f"Görev ödülü alındı: {quest.reward_points} puan.",ephemeral=True)
        except Exception:
            db.session.rollback(); log.exception("Quest reward claim failed")
            if not interaction.response.is_done(): await interaction.response.send_message("Ödül alınamadı. İşlem kaydı kontrol edilmeli; aynı ödül ikinci kez verilmez.",ephemeral=True)

    @app_commands.command(name="dukkanurunekle", description="Mağazaya ürün ekle (yönetici).")
    async def add_shop_item(self, interaction: discord.Interaction, anahtar: str, baslik: str, fiyat: app_commands.Range[int,0,1000000], aciklama: str, tur: str="cosmetic", rol: discord.Role | None=None, sure_gun: app_commands.Range[int,1,3650] | None=None):
        if not is_admin(interaction):
            await interaction.response.send_message("Yönetici yetkisi gerekiyor.",ephemeral=True); return
        if not anahtar.replace("_","").replace("-","").isalnum() or len(anahtar)>80 or len(baslik)>120 or len(aciklama)>300 or tur not in {"cosmetic","role","badge","collection"}:
            await interaction.response.send_message("Ürün alanları geçersiz.",ephemeral=True); return
        if tur=="role" and rol is None:
            await interaction.response.send_message("Rol ürünü için Discord rolü seçilmeli.",ephemeral=True); return
        if rol and interaction.guild and interaction.guild.me and rol >= interaction.guild.me.top_role:
            await interaction.response.send_message("Botun rol hiyerarşisi bu rolü veremiyor.",ephemeral=True); return
        app=create_app()
        with app.app_context():
            existing=db.session.execute(select(RewardShopItem.id).where(RewardShopItem.key==anahtar)).scalar_one_or_none()
            if existing:
                await interaction.response.send_message("Bu ürün anahtarı zaten kullanılıyor.",ephemeral=True); return
            db.session.add(RewardShopItem(key=anahtar,title=baslik.strip(),description=aciklama.strip(),item_type=tur,price=int(fiyat),discord_role_id=str(rol.id) if rol else None,duration_days=int(sure_gun) if sure_gun else None,enabled=True))
            db.session.add(AuditLog(actor_discord_id=str(interaction.user.id),action="shop.item_created",target_type="shop_item",target_id=anahtar,details={"price":int(fiyat),"type":tur},success=True))
            db.session.commit()
        await interaction.response.send_message(f"Mağaza ürünü eklendi: {baslik} ({fiyat} puan).",ephemeral=True)

    @app_commands.command(name="dukkanal", description="Mağazadan bir koleksiyon ürünü satın al.")
    async def buy_shop_item(self, interaction: discord.Interaction, urun: str):
        app=create_app(); added_role=None
        try:
            with app.app_context():
                item=db.session.execute(select(RewardShopItem).where(RewardShopItem.key==urun,RewardShopItem.enabled.is_(True))).scalar_one_or_none()
                if not item:
                    await interaction.response.send_message("Ürün bulunamadı. Mağazayı kontrol et.",ephemeral=True); return
                existing=db.session.execute(select(MemberCollectionItem.id).where(MemberCollectionItem.discord_id==str(interaction.user.id),MemberCollectionItem.item_key==item_key, (MemberCollectionItem.expires_at.is_(None)) | (MemberCollectionItem.expires_at>utcnow()))).scalar_one_or_none()
                if existing:
                    await interaction.response.send_message("Bu ürüne zaten sahipsin.",ephemeral=True); return
                profile=db.session.execute(select(UserProfile).where(UserProfile.discord_id==str(interaction.user.id))).scalar_one_or_none()
                if not profile:
                    profile=UserProfile(discord_id=str(interaction.user.id),balance=0); db.session.add(profile); db.session.flush()
                if profile.balance < item.price:
                    await interaction.response.send_message("Yeterli puanın yok.",ephemeral=True); return
                role=None
                if item.item_type=="role":
                    if not item.discord_role_id or not isinstance(interaction.user,discord.Member):
                        await interaction.response.send_message("Rol ürünü yapılandırılmamış.",ephemeral=True); return
                    role=interaction.guild.get_role(int(item.discord_role_id)) if interaction.guild else None
                    if not role or not interaction.guild.me.guild_permissions.manage_roles or role>=interaction.guild.me.top_role:
                        await interaction.response.send_message("Botun bu rolü verme izni veya rol hiyerarşisi uygun değil.",ephemeral=True); return
                changed=db.session.execute(update(UserProfile).where(UserProfile.discord_id==str(interaction.user.id),UserProfile.balance>=item.price).values(balance=UserProfile.balance-item.price))
                if changed.rowcount!=1:
                    db.session.rollback(); await interaction.response.send_message("Yeterli puanın yok.",ephemeral=True); return
                profile=db.session.execute(select(UserProfile).where(UserProfile.discord_id==str(interaction.user.id))).scalar_one()
                db.session.add(EconomyTransaction(user_id=profile.id,amount=-item.price,balance_after=profile.balance,transaction_type="shop_purchase",description=f"Shop item: {item.key}",actor_discord_id=str(interaction.user.id),idempotency_key=f"shop:{interaction.user.id}:{item.key}:{int(utcnow().timestamp())}"))
                expiry=utcnow()+timedelta(days=item.duration_days) if item.duration_days else None
                db.session.add(MemberCollectionItem(discord_id=str(interaction.user.id),item_key=item.key,source="purchase",expires_at=expiry))
                db.session.add(AuditLog(actor_discord_id=str(interaction.user.id),action="shop.purchase",target_type="shop_item",target_id=item.key,details={"price":item.price},success=True))
                db.session.commit()
                title=item.title; price=int(item.price); item_key=item.key; role_id=item.discord_role_id if item.item_type=="role" else None
            if role_id and isinstance(interaction.user,discord.Member):
                role=interaction.guild.get_role(int(role_id))
                try: await interaction.user.add_roles(role,reason="Kaplumbik shop purchase")
                except discord.HTTPException:
                    with app.app_context():
                        adjust_balance(str(interaction.user.id),price,"shop_refund",f"Rol ürünü verilemedi: {item_key}",actor_discord_id="kaplumbik",idempotency_key=f"shop-refund:{interaction.user.id}:{item_key}:{int(utcnow().timestamp())}")
                        row=db.session.execute(select(MemberCollectionItem).where(MemberCollectionItem.discord_id==str(interaction.user.id),MemberCollectionItem.item_key==item.key)).scalar_one_or_none()
                        if row: db.session.delete(row)
                        db.session.commit()
                    await interaction.response.send_message("Rol verilemedi; puan iadesi yapıldı.",ephemeral=True); return
            await interaction.response.send_message(f"Satın alındı: {title}. Harcanan puan: {price}.",ephemeral=True)
        except IntegrityError:
            db.session.rollback()
            await interaction.response.send_message("Satın alma çakıştı; veritabanı işlemi geri alındı.",ephemeral=True)
        except Exception:
            db.session.rollback(); log.exception("Shop purchase failed")
            if not interaction.response.is_done(): await interaction.response.send_message("Satın alma tamamlanamadı. İşlem kaydı kontrol edilmeli.",ephemeral=True)

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

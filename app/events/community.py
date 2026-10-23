import logging
import asyncio
import json
import requests
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import discord
from discord import app_commands
from discord.ext import commands, tasks
from sqlalchemy import select, func, update
from sqlalchemy.exc import IntegrityError
from app import create_app
from app.core.config import settings
from app.database import db
from app.database.community_models import MemberGameProfile, CommunityPoll, CommunityPollVote, CommunitySuggestion, CommunitySuggestionVote, WeeklyQuest, WeeklyQuestProgress, RewardShopItem, MemberCollectionItem, MemberShopPreference, FeaturePermission, ServerMemoryProposal
from app.database.models import AuditLog, EconomyTransaction, UserProfile
from app.database.advanced_models import BotSetting
from app.events.feature_service import get_setting

log = logging.getLogger("kaplumbik.community")
TR = ZoneInfo("Europe/Istanbul")

def _parse_poll_suggestion(raw):
    """Parse and validate the JSON object returned by the poll-suggestion model."""
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("AI returned empty poll suggestion text")
    candidate = raw.strip()
    start = candidate.find("{")
    end = candidate.rfind("}")
    if start < 0 or end < start:
        raise ValueError("AI response did not contain a JSON object")
    parsed = json.loads(candidate[start:end + 1])
    if not isinstance(parsed, dict):
        raise ValueError("AI response JSON was not an object")
    question = parsed.get("question")
    options = parsed.get("options")
    if not isinstance(question, str) or not isinstance(options, list):
        raise ValueError("AI response must contain a question and an options list")
    clean_options = list(dict.fromkeys(
        value.strip()[:80] for value in options
        if isinstance(value, str) and value.strip()
    ))[:5]
    result = {"question": question.strip()[:300], "options": clean_options}
    if not result["question"] or len(clean_options) < 2:
        raise ValueError("AI output did not contain a valid question and at least two options")
    return result


def utcnow():
    return datetime.now(timezone.utc)

def as_utc(value):
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)

def is_expired(value, now=None):
    normalized = as_utc(value)
    return bool(normalized and normalized <= (now or utcnow()))

def is_owner(i):
    return bool(settings.owner_discord_id) and str(i.user.id) == str(settings.owner_discord_id)

def is_admin(i):
    return is_owner(i) or (isinstance(i.user, discord.Member) and i.user.guild_permissions.administrator)


def can_manage_module(interaction,module_key):
    if is_admin(interaction): return True
    if not isinstance(interaction.user,discord.Member): return False
    role_ids={str(role.id) for role in interaction.user.roles}
    app=create_app()
    with app.app_context():
        rows=db.session.execute(select(FeaturePermission).where(FeaturePermission.module_key==module_key,FeaturePermission.can_manage.is_(True))).scalars().all()
        return any(row.discord_role_id in role_ids for row in rows)

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
                if not poll or poll.status != "open" or is_expired(poll.ends_at):
                    await interaction.response.send_message("Bu anket artık açık değil.",ephemeral=True); return
                vote=db.session.execute(select(CommunityPollVote).where(CommunityPollVote.poll_id==poll.id,CommunityPollVote.discord_id==str(interaction.user.id))).scalar_one_or_none()
                if vote: vote.option_index=idx
                else: db.session.add(CommunityPollVote(poll_id=poll.id,discord_id=str(interaction.user.id),option_index=idx))
                db.session.commit()
            await interaction.response.send_message("Oyun kaydedildi. Tekrar oy vererek seçimini değiştirebilirsin.",ephemeral=True)
        return callback

class MahzenCommunity(commands.Cog):
    def __init__(self, bot): self.bot=bot
    async def cog_load(self):
        if not self.expire_shop_items.is_running():
            self.expire_shop_items.start()
        app = create_app()
        with app.app_context():
            polls = db.session.execute(select(CommunityPoll).where(CommunityPoll.status == "open")).scalars().all()
            active = [(poll.id, list(poll.options), poll.message_id) for poll in polls]
        for poll_id, options, message_id in active:
            try:
                self.bot.add_view(PollView(poll_id, options), message_id=int(message_id) if message_id else None)
            except (ValueError, discord.HTTPException):
                log.exception("Could not restore persistent poll view %s", poll_id)

    def cog_unload(self):
        self.expire_shop_items.cancel()



    @app_commands.command(name="sunucuhafizaoner", description="Mahzen için ortak bilgi öner; yönetici onaylamadan AI hafızasına eklenmez.")
    async def propose_server_memory(self, interaction: discord.Interaction, bilgi: app_commands.Range[str,10,1000]):
        if not interaction.guild_id:
            await interaction.response.send_message("Bu komut yalnızca sunucuda kullanılabilir.",ephemeral=True); return
        app=create_app()
        with app.app_context():
            row=ServerMemoryProposal(guild_id=str(interaction.guild_id),proposer_id=str(interaction.user.id),content=bilgi.strip(),status="pending")
            db.session.add(row); db.session.commit(); proposal_id=row.id
        await interaction.response.send_message(f"Ortak bilgi önerin #{proposal_id} olarak kaydedildi. Yönetici inceleyip onaylamadan AI tarafından doğrulanmış bilgi sayılmaz. Kişisel veya hassas bilgi ekleme.",ephemeral=True)


    @app_commands.command(name="sunucuhafizabekleyen", description="Onay bekleyen ortak bilgi önerilerini listele (AI yönetimi izni).")
    async def pending_server_memories(self, interaction: discord.Interaction):
        if not can_manage_module(interaction,"ai"):
            await interaction.response.send_message("AI/ortak hafıza yönetimi izni gerekiyor.",ephemeral=True); return
        app=create_app()
        with app.app_context():
            rows=db.session.execute(select(ServerMemoryProposal).where(ServerMemoryProposal.status=="pending").order_by(ServerMemoryProposal.created_at.asc()).limit(10)).scalars().all()
            snapshot=[(row.id,row.proposer_id,row.content,row.created_at) for row in rows]
        if not snapshot:
            await interaction.response.send_message("Onay bekleyen ortak bilgi önerisi yok.",ephemeral=True); return
        lines=[f"#{sid} · gönderen ID {uid} · {created.astimezone(TR).strftime('%d.%m %H:%M')}\n{content}" for sid,uid,content,created in snapshot]
        await interaction.response.send_message("Onay bekleyen ortak bilgiler\n"+"\n\n".join(lines)[:1850],ephemeral=True)

    @app_commands.command(name="sunucuhafizayonet", description="Ortak bilgi önerisini onayla veya reddet (yönetici).")
    @app_commands.choices(karar=[app_commands.Choice(name="Onayla ve ekle",value="approved"),app_commands.Choice(name="Reddet",value="rejected")])
    async def review_server_memory(self, interaction: discord.Interaction, onerino: int, karar: app_commands.Choice[str]):
        if not can_manage_module(interaction,"ai"):
            await interaction.response.send_message("AI/ortak hafıza yönetimi izni gerekiyor.",ephemeral=True); return
        app=create_app()
        with app.app_context():
            proposal=db.session.get(ServerMemoryProposal,onerino)
            if not proposal or proposal.status!="pending":
                await interaction.response.send_message("Bekleyen öneri bulunamadı veya daha önce incelendi.",ephemeral=True); return
            if karar.value=="approved":
                current=get_setting("server_knowledge","").strip()
                addition=f"\n- Yönetici onaylı ortak bilgi (öneri #{proposal.id}, {datetime.now(TR).strftime('%Y-%m-%d')}): {proposal.content}"
                if len(current)+len(addition)>8000:
                    await interaction.response.send_message("Sunucu bilgi alanı dolu. Önce panelden eski bilgileri düzenle.",ephemeral=True); return
                knowledge_row=db.session.get(BotSetting,"server_knowledge")
                if knowledge_row is None: knowledge_row=BotSetting(key="server_knowledge",value=current+addition,updated_by=str(interaction.user.id)); db.session.add(knowledge_row)
                else: knowledge_row.value=current+addition; knowledge_row.updated_by=str(interaction.user.id)
            proposal.status=karar.value; proposal.reviewed_by=str(interaction.user.id); proposal.reviewed_at=utcnow()
            db.session.add(AuditLog(actor_discord_id=str(interaction.user.id),action="ai.server_memory_review",target_type="server_memory_proposal",target_id=str(proposal.id),details={"decision":karar.value},success=True)); db.session.commit()
        await interaction.response.send_message(f"Ortak bilgi önerisi #{onerino}: {karar.name}.",ephemeral=True)

    @app_commands.command(name="takvim", description="Önümüzdeki 7 günün Mahzen etkinlik takvimini göster.")
    async def event_calendar(self, interaction: discord.Interaction):
        from app.database.event_models import Event
        app=create_app()
        with app.app_context():
            start=utcnow(); end=start+timedelta(days=7)
            events=db.session.execute(select(Event).where(Event.status=="scheduled",Event.starts_at>=start,Event.starts_at<=end).order_by(Event.starts_at.asc()).limit(20)).scalars().all()
            snapshot=[(e.id,e.title,e.game,e.starts_at,e.description) for e in events]
        if not snapshot:
            await interaction.response.send_message("Önümüzdeki 7 gün için planlanmış etkinlik yok. Yeni etkinlikler eklenince burada görünecek.",ephemeral=False); return
        lines=[]
        for event_id,title,game,starts,description in snapshot:
            if starts.tzinfo is None: starts=starts.replace(tzinfo=timezone.utc)
            lines.append(f"<t:{int(starts.timestamp())}:F> · **{title}** ({game})"+(f"\n{description[:120]}" if description else "")+f" · etkinlik #{event_id}")
        await interaction.response.send_message("📅 **Mahzen etkinlik takvimi · 7 gün**\n"+"\n".join(lines)[:1900],allowed_mentions=discord.AllowedMentions.none())

    @app_commands.command(name="puangecmisi", description="Kendi puan hareketlerinin son 10 kaydını göster.")
    async def point_history(self, interaction: discord.Interaction):
        app=create_app()
        with app.app_context():
            profile=db.session.execute(select(UserProfile).where(UserProfile.discord_id==str(interaction.user.id))).scalar_one_or_none()
            if not profile:
                await interaction.response.send_message("Henüz puan hesabın yok.",ephemeral=True); return
            rows=db.session.execute(select(EconomyTransaction).where(EconomyTransaction.user_id==profile.id).order_by(EconomyTransaction.created_at.desc()).limit(10)).scalars().all()
            balance=profile.balance
            snapshot=[(x.amount,x.description,x.created_at,x.balance_after) for x in rows]
        lines=[]
        for amount,description,created,balance_after in snapshot:
            if created.tzinfo is None: created=created.replace(tzinfo=timezone.utc)
            lines.append(f"{'+' if amount>0 else ''}{amount} · {description[:90]} · bakiye {balance_after} · <t:{int(created.timestamp())}:R>")
        await interaction.response.send_message(f"💰 **Puan geçmişin** · güncel bakiye: {balance}\n"+("\n".join(lines) if lines else "Henüz işlem yok."),ephemeral=True)

    @app_commands.command(name="izinprova", description="Bir üyenin kanaldaki izinlerini değişiklik yapmadan simüle et.")
    async def permission_simulation(self, interaction: discord.Interaction, uye: discord.Member, kanal: discord.TextChannel):
        if not is_admin(interaction):
            await interaction.response.send_message("İzin simülasyonu yalnızca sunucu sahibi veya Administrator yetkilisine açık.",ephemeral=True); return
        permissions=kanal.permissions_for(uye)
        role_ids={str(role.id) for role in uye.roles}
        app=create_app()
        with app.app_context():
            module_rows=db.session.execute(select(FeaturePermission).where(FeaturePermission.can_manage.is_(True))).scalars().all()
            modules=sorted({row.module_key for row in module_rows if row.discord_role_id in role_ids})
        checks=[
            ("Kanalı görüntüleme",permissions.view_channel),("Mesaj gönderme",permissions.send_messages),
            ("Mesajları yönetme",permissions.manage_messages),("@everyone/@here",permissions.mention_everyone),
            ("Rol yönetimi",permissions.manage_roles),("Üyeleri timeout",permissions.moderate_members),
            ("Administrator",permissions.administrator),
        ]
        lines=[("✅" if allowed else "❌")+" "+label for label,allowed in checks]
        lines.append("Modül rol kayıtları: "+(", ".join(modules) if modules else "yok"))
        lines.append("Bu işlem yalnızca rapor üretir; hiçbir rol veya izin değiştirilmedi.")
        await interaction.response.send_message(f"🧪 **İzin provası** · {uye.mention} · {kanal.mention}\n"+"\n".join(lines),ephemeral=True,allowed_mentions=discord.AllowedMentions.none())

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


    @app_commands.command(name="anketoner", description="Bir konu için AI'dan anket taslağı iste; hiçbir şey otomatik yayımlanmaz.")
    async def suggest_poll(self, interaction: discord.Interaction, konu: str):
        if not settings.openrouter_api_key or not settings.openrouter_model:
            await interaction.response.send_message("AI anket önerisi için OPENROUTER_API_KEY ve OPENROUTER_MODEL ayarlanmalı.",ephemeral=True); return
        if not konu.strip() or len(konu)>300:
            await interaction.response.send_message("Konu 1–300 karakter olmalı.",ephemeral=True); return
        await interaction.response.defer(thinking=True,ephemeral=True)
        def request_suggestion():
            response=requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={"Authorization":f"Bearer {settings.openrouter_api_key}","Content-Type":"application/json"},
                json={
                    "model":settings.openrouter_model,
                    "temperature":0.5,
                    "max_tokens":350,
                    "messages":[
                        {"role":"system","content":'Türkçe Discord topluluğu için tarafsız, kısa anket taslağı üret. Yalnızca geçerli JSON döndür: {"question":"...","options":["...","..."]}. 2-5 kısa seçenek. Siyasi/kişisel hassas veri sorma.'},
                        {"role":"user","content":f"Konu: {konu.strip()}"},
                    ],
                },
                timeout=25,
            )
            response.raise_for_status()
            data=response.json()
            choices=data.get("choices")
            if not isinstance(choices,list) or not choices or not isinstance(choices[0],dict):
                raise ValueError("OpenRouter response did not contain a choice")
            message=choices[0].get("message")
            if not isinstance(message,dict):
                raise ValueError("OpenRouter response did not contain a message")
            content=message.get("content")
            if isinstance(content,list):
                content="".join(
                    part.get("text","") for part in content
                    if isinstance(part,dict) and isinstance(part.get("text"),str)
                )
            if not isinstance(content,str) or not content.strip():
                finish_reason=choices[0].get("finish_reason","unknown")
                raise ValueError(f"OpenRouter returned empty text content (finish_reason={finish_reason})")
            return content

        try:
            raw=await asyncio.to_thread(request_suggestion)
            parsed=_parse_poll_suggestion(raw)
            question=parsed["question"]
            options=parsed["options"]
            await interaction.followup.send("Anket taslağı (henüz yayımlanmadı):\nSoru: "+question+"\nSeçenekler: "+" | ".join(options)+"\nİstersen bu metni /anket komutunda kullan.",ephemeral=True)
        except Exception:
            log.exception("AI poll suggestion failed")
            await interaction.followup.send("Anket önerisi oluşturulamadı. Model ayarlarını kontrol et veya konuyu değiştir.",ephemeral=True)

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


    @app_commands.command(name="anketsonuc", description="Bir anketin oy sayılarını göster.")
    async def poll_results(self, interaction: discord.Interaction, anketno: int):
        app=create_app()
        with app.app_context():
            poll=db.session.get(CommunityPoll,anketno)
            if not poll:
                await interaction.response.send_message("Anket bulunamadı.",ephemeral=True); return
            if is_expired(poll.ends_at) and poll.status=="open":
                poll.status="closed"; db.session.commit()
            counts=[db.session.scalar(select(func.count(CommunityPollVote.id)).where(CommunityPollVote.poll_id==poll.id,CommunityPollVote.option_index==idx)) or 0 for idx,_ in enumerate(poll.options)]
            total=sum(counts)
            question=poll.question; options=list(poll.options); status=poll.status
        lines=[f"{option}: **{count}** oy ({round(count*100/total) if total else 0}%)" for option,count in zip(options,counts)]
        await interaction.response.send_message(f"📊 **Anket #{anketno}: {question}** · durum: {status}\nToplam oy: {total}\n"+"\n".join(lines),ephemeral=False,allowed_mentions=discord.AllowedMentions.none())

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
        if not can_manage_module(interaction,"suggestions"):
            await interaction.response.send_message("Öneri yönetimi izni gerekiyor.",ephemeral=True); return
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
        type_labels={"cosmetic":"Unvan","role":"Discord rolü","badge":"Rozet","collection":"Koleksiyon"}
        await interaction.response.send_message("**Mahzen mağazası**\n"+"\n\n".join(f"**{x.title}** · {x.price} coin · {type_labels.get(x.item_type, x.item_type)}\nAnahtar: \x60{x.key}\x60\n{x.description or 'Açıklama yok'}" for x in items),ephemeral=True)

    @app_commands.command(name="envanter", description="Satın aldığın tüm mağaza ürünlerini görüntüle.")
    async def shop_inventory(self, interaction: discord.Interaction):
        app=create_app()
        with app.app_context():
            rows=db.session.execute(
                select(MemberCollectionItem, RewardShopItem)
                .join(RewardShopItem, MemberCollectionItem.item_key==RewardShopItem.key)
                .where(MemberCollectionItem.discord_id==str(interaction.user.id))
                .order_by(MemberCollectionItem.acquired_at.desc())
                .limit(100)
            ).all()
            snapshot=[(entry.item_key, item.title, item.item_type, entry.source, entry.expires_at) for entry,item in rows if not is_expired(entry.expires_at)]
        labels={"cosmetic":"Unvan","role":"Rol","badge":"Rozet","collection":"Koleksiyon"}
        lines=[f"**{title}** · {labels.get(kind,kind)} · \x60{key}\x60"+(f" · bitiş {as_utc(expiry).astimezone(TR).strftime('%d.%m.%Y')}" if expiry else " · kalıcı") for key,title,kind,source,expiry in snapshot]
        await interaction.response.send_message("**Envanterin**\n"+("\n".join(lines) if lines else "Henüz mağazadan ürün almadın."),ephemeral=True)

    @app_commands.command(name="koleksiyon", description="Sahip olduğun koleksiyon ürünlerini görüntüle.")
    async def collection(self, interaction: discord.Interaction):
        app=create_app()
        with app.app_context():
            rows=db.session.execute(
                select(MemberCollectionItem, RewardShopItem)
                .join(RewardShopItem, MemberCollectionItem.item_key==RewardShopItem.key)
                .where(MemberCollectionItem.discord_id==str(interaction.user.id), RewardShopItem.item_type=="collection")
                .order_by(MemberCollectionItem.acquired_at.desc())
                .limit(50)
            ).all()
            snapshot=[(entry.item_key,item.title,entry.expires_at) for entry,item in rows if not is_expired(entry.expires_at)]
        lines=[f"**{title}** · \x60{key}\x60"+(f" · bitiş {as_utc(expiry).astimezone(TR).strftime('%d.%m.%Y')}" if expiry else " · kalıcı") for key,title,expiry in snapshot]
        await interaction.response.send_message("**Koleksiyonun**\n"+("\n".join(lines) if lines else "Henüz koleksiyon ürünü edinmedin."),ephemeral=True)

    @app_commands.command(name="rozetler", description="Satın aldığın rozetleri görüntüle.")
    async def shop_badges(self, interaction: discord.Interaction):
        app=create_app()
        with app.app_context():
            rows=db.session.execute(
                select(MemberCollectionItem, RewardShopItem)
                .join(RewardShopItem, MemberCollectionItem.item_key==RewardShopItem.key)
                .where(MemberCollectionItem.discord_id==str(interaction.user.id), RewardShopItem.item_type=="badge")
                .order_by(MemberCollectionItem.acquired_at.desc())
                .limit(50)
            ).all()
            snapshot=[(entry.item_key,item.title,item.description,entry.expires_at) for entry,item in rows if not is_expired(entry.expires_at)]
        lines=[f"**{title}** · \x60{key}\x60"+(f" — {description}" if description else "") for key,title,description,expiry in snapshot]
        await interaction.response.send_message("**Rozetlerin**\n"+("\n".join(lines) if lines else "Henüz mağazadan rozet almadın."),ephemeral=True)

    @app_commands.command(name="unvan", description="Satın aldığın kozmetik unvanı görüntüle, seç veya kaldır.")
    @app_commands.describe(unvan="Ürün anahtarı ya da unvan adı; 'kaldir' yazarak kaldırabilirsin.")
    async def shop_title(self, interaction: discord.Interaction, unvan: str | None = None):
        if interaction.guild_id is None:
            await interaction.response.send_message("Bu komut sunucu içinde kullanılmalı.",ephemeral=True); return
        app=create_app()
        with app.app_context():
            member_id=str(interaction.user.id)
            guild_id=str(interaction.guild_id)
            preference=db.session.execute(select(MemberShopPreference).where(MemberShopPreference.guild_id==guild_id,MemberShopPreference.discord_id==member_id)).scalar_one_or_none()
            if unvan is None:
                owned=db.session.execute(
                    select(MemberCollectionItem,RewardShopItem)
                    .join(RewardShopItem,MemberCollectionItem.item_key==RewardShopItem.key)
                    .where(MemberCollectionItem.discord_id==member_id,RewardShopItem.item_type=="cosmetic")
                    .order_by(MemberCollectionItem.acquired_at.desc())
                ).all()
                owned=[(entry,item) for entry,item in owned if not is_expired(entry.expires_at)]
                active_key=preference.active_title_key if preference else None
                active_item=next((item for entry,item in owned if item.key==active_key),None)
                available=", ".join(f"{item.title} (\x60{item.key}\x60)" for entry,item in owned) or "Henüz kozmetik unvanın yok."
                await interaction.response.send_message(f"**Aktif unvan:** {active_item.title if active_item else 'Yok'}\n**Sahip olduğun unvanlar:** {available}\nUnvan seçmek için \x60/unvan unvan:<ürün anahtarı>\x60 kullan. Kaldırmak için \x60/unvan unvan:kaldir\x60 yaz.",ephemeral=True)
                return
            if unvan.casefold().strip()=="kaldir":
                if preference:
                    preference.active_title_key=None
                    db.session.commit()
                await interaction.response.send_message("Aktif kozmetik unvanın kaldırıldı.",ephemeral=True); return
            owned=db.session.execute(
                select(MemberCollectionItem,RewardShopItem)
                .join(RewardShopItem,MemberCollectionItem.item_key==RewardShopItem.key)
                .where(MemberCollectionItem.discord_id==member_id,RewardShopItem.item_type=="cosmetic")
            ).all()
            match=next(((entry,item) for entry,item in owned if not is_expired(entry.expires_at) and (item.key.casefold()==unvan.casefold().strip() or item.title.casefold()==unvan.casefold().strip())),None)
            if not match:
                await interaction.response.send_message("Bu unvana sahip değilsin. Önce mağazadan satın al; ürün anahtarını \x60/envanter\x60 komutundan görebilirsin.",ephemeral=True); return
            entry,item=match
            if preference is None:
                preference=MemberShopPreference(guild_id=guild_id,discord_id=member_id,active_title_key=item.key)
                db.session.add(preference)
            else:
                preference.active_title_key=item.key
            db.session.commit()
            title=item.title
        await interaction.response.send_message(f"Aktif unvanın **{title}** olarak ayarlandı. Profilinde görünür.",ephemeral=True)


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


    @app_commands.command(name="goreval", description="Tamamladığın haftalık görevin puanını al.")
    async def claim_quest(self, interaction: discord.Interaction, gorev: int):
        app=create_app()
        try:
            with app.app_context():
                quest=db.session.get(WeeklyQuest,gorev)
                if not quest or not quest.enabled or is_expired(quest.ends_at):
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
                reward_key=f"quest:{quest.id}:{interaction.user.id}"
                try:
                    adjust_balance(str(interaction.user.id),int(quest.reward_points),"weekly_quest",f"Haftalık görev: {quest.title}",actor_discord_id="kaplumbik",idempotency_key=reward_key)
                except DuplicateTransactionError:
                    already=db.session.execute(select(EconomyTransaction.id).where(EconomyTransaction.idempotency_key==reward_key)).scalar_one_or_none()
                    if already is None: raise
                progress.claimed_at=utcnow()
                db.session.add(AuditLog(actor_discord_id=str(interaction.user.id),action="quest.reward_claimed",target_type="quest",target_id=str(quest.id),details={"reward":quest.reward_points},success=True))
                db.session.commit()
            await interaction.response.send_message(f"Görev ödülü alındı: {quest.reward_points} puan.",ephemeral=True)
        except Exception:
            db.session.rollback(); log.exception("Quest reward claim failed")
            if not interaction.response.is_done(): await interaction.response.send_message("Ödül alınamadı. İşlem kaydı kontrol edilmeli; aynı ödül ikinci kez verilmez.",ephemeral=True)

    @app_commands.command(name="dukkanurunekle", description="Mağazaya ürün ekle (yönetici).")
    async def add_shop_item(self, interaction: discord.Interaction, anahtar: str, baslik: str, fiyat: app_commands.Range[int,0,1000000], aciklama: str, tur: str="cosmetic", rol: discord.Role | None=None, sure_gun: app_commands.Range[int,1,3650] | None=None):
        if not can_manage_module(interaction,"economy"):
            await interaction.response.send_message("Ekonomi modülü yönetim izni gerekiyor.",ephemeral=True); return
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
                expired_rows=db.session.execute(select(MemberCollectionItem).where(MemberCollectionItem.discord_id==str(interaction.user.id),MemberCollectionItem.item_key==item.key,MemberCollectionItem.expires_at.is_not(None),MemberCollectionItem.expires_at<=utcnow())).scalars().all()
                for expired_row in expired_rows: db.session.delete(expired_row)
                db.session.flush()
                existing=db.session.execute(select(MemberCollectionItem.id).where(MemberCollectionItem.discord_id==str(interaction.user.id),MemberCollectionItem.item_key==item.key, (MemberCollectionItem.expires_at.is_(None)) | (MemberCollectionItem.expires_at>utcnow()))).scalar_one_or_none()
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
                        row=db.session.execute(select(MemberCollectionItem).where(MemberCollectionItem.discord_id==str(interaction.user.id),MemberCollectionItem.item_key==item_key)).scalar_one_or_none()
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


    @tasks.loop(minutes=15)
    async def expire_shop_items(self):
        await self.bot.wait_until_ready()
        app=create_app()
        with app.app_context():
            rows=db.session.execute(select(MemberCollectionItem,RewardShopItem).join(RewardShopItem,MemberCollectionItem.item_key==RewardShopItem.key).where(MemberCollectionItem.expires_at.is_not(None),MemberCollectionItem.expires_at<=utcnow())).all()
            snapshot=[(entry.id,entry.discord_id,entry.item_key,item.item_type,item.discord_role_id) for entry,item in rows]
        for entry_id,discord_id,item_key,item_type,role_id in snapshot:
            if item_type=="role" and role_id and role_id.isdigit():
                member=None; guild_for_member=None
                for guild in self.bot.guilds:
                    member=guild.get_member(int(discord_id))
                    if member: guild_for_member=guild; break
                if member and guild_for_member:
                    role=guild_for_member.get_role(int(role_id))
                    if role and role in member.roles:
                        try: await member.remove_roles(role,reason="Kaplumbik shop role expired")
                        except discord.HTTPException:
                            log.exception("Could not remove expired shop role %s from %s",role_id,discord_id)
                            continue
            app=create_app()
            with app.app_context():
                row=db.session.get(MemberCollectionItem,entry_id)
                if row:
                    db.session.add(AuditLog(actor_discord_id="kaplumbik",action="shop.item_expired",target_type="member_collection",target_id=f"{discord_id}:{item_key}",details={"type":item_type},success=True))
                    db.session.delete(row); db.session.commit()

    @expire_shop_items.before_loop
    async def before_expire_shop_items(self): await self.bot.wait_until_ready()

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
            local_day=datetime.now(TR).date().isoformat()
            day_quests=db.session.execute(select(WeeklyQuest).where(WeeklyQuest.enabled.is_(True),WeeklyQuest.starts_at<=now,WeeklyQuest.ends_at>now,WeeklyQuest.quest_type=="active_days")).scalars().all()
            for q in day_quests:
                p=db.session.execute(select(WeeklyQuestProgress).where(WeeklyQuestProgress.quest_id==q.id,WeeklyQuestProgress.discord_id==str(message.author.id))).scalar_one_or_none()
                if not p: p=WeeklyQuestProgress(quest_id=q.id,discord_id=str(message.author.id),progress=0); db.session.add(p)
                if p.last_activity_day != local_day:
                    p.progress=min(q.target,p.progress+1); p.last_activity_day=local_day
            shared=db.session.execute(select(WeeklyQuest).where(WeeklyQuest.enabled.is_(True),WeeklyQuest.starts_at<=now,WeeklyQuest.ends_at>now,WeeklyQuest.quest_type=="shared_members")).scalars().all()
            for q in shared:
                p=db.session.execute(select(WeeklyQuestProgress).where(WeeklyQuestProgress.quest_id==q.id,WeeklyQuestProgress.discord_id==str(message.author.id))).scalar_one_or_none()
                if not p: db.session.add(WeeklyQuestProgress(quest_id=q.id,discord_id=str(message.author.id),progress=1))
            db.session.commit()

async def setup(bot):
    await bot.add_cog(MahzenCommunity(bot))

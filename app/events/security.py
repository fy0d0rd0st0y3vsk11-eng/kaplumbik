import logging
import asyncio
from collections import deque
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from discord.ext import commands, tasks
from sqlalchemy import select

from app import create_app
from app.core.config import settings
from app.database import db
from app.database.advanced_models import BotSetting
from app.database.models import AuditLog

log=logging.getLogger("kaplumbik.security")
TR=ZoneInfo("Europe/Istanbul")

def setting(key,default=""):
    row=db.session.get(BotSetting,key)
    return (row.value or "").strip() if row else default

def set_setting(key,value,actor=None):
    row=db.session.get(BotSetting,key)
    if row is None:
        row=BotSetting(key=key,value=str(value)); db.session.add(row)
    else: row.value=str(value)
    row.updated_by=str(actor) if actor else None
    db.session.commit()

def owner(interaction):
    return bool(settings.owner_discord_id) and str(interaction.user.id)==str(settings.owner_discord_id)

def admin(interaction):
    return owner(interaction) or (isinstance(interaction.user,discord.Member) and interaction.user.guild_permissions.administrator)

class VerificationView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
    @discord.ui.button(label="Kuralları kabul et ve doğrulan",style=discord.ButtonStyle.success,custom_id="kaplumbik:verify")
    async def verify(self,interaction:discord.Interaction,button:discord.ui.Button):
        if not isinstance(interaction.user,discord.Member) or interaction.guild is None:
            await interaction.response.send_message("Bu düğme yalnızca sunucuda kullanılabilir.",ephemeral=True); return
        app=create_app()
        with app.app_context():
            unverified=setting("unverified_role_id","")
            member_role=setting("member_role_id","")
        try:
            if unverified.isdigit():
                role=interaction.guild.get_role(int(unverified))
                if role and role in interaction.user.roles: await interaction.user.remove_roles(role,reason="Kaplumbik verification")
            if member_role.isdigit():
                role=interaction.guild.get_role(int(member_role))
                if role and role not in interaction.user.roles: await interaction.user.add_roles(role,reason="Kaplumbik verification")
            await interaction.response.send_message("Doğrulama tamamlandı. Mahzen'e hoş geldin!",ephemeral=True)
        except discord.HTTPException:
            if not interaction.response.is_done(): await interaction.response.send_message("Roller güncellenemedi. Yönetici bot izinlerini kontrol etmeli.",ephemeral=True)

class SecurityCog(commands.Cog):
    def __init__(self,bot):
        self.bot=bot
        self.joins=deque()
        self.deletions=deque()

    async def cog_load(self):
        self.bot.add_view(VerificationView())
        if not self.unverified_watch.is_running(): self.unverified_watch.start()

    def cog_unload(self):
        self.unverified_watch.cancel()

    async def alert_owner(self,text):
        if not settings.owner_discord_id or not str(settings.owner_discord_id).isdigit(): return
        user=self.bot.get_user(int(settings.owner_discord_id))
        if user is None:
            try: user=await self.bot.fetch_user(int(settings.owner_discord_id))
            except discord.HTTPException: return
        try: await user.send(text[:1800])
        except discord.HTTPException: log.warning("Could not DM owner for security alert.")

    @commands.Cog.listener()
    async def on_member_join(self,member):
        if member.bot: return
        now=datetime.now(timezone.utc)
        while self.joins and (now-self.joins[0]).total_seconds()>30: self.joins.popleft()
        self.joins.append(now)
        app=create_app()
        with app.app_context():
            unverified_id=setting("unverified_role_id","")
            verify_channel_id=setting("verification_channel_id","")
            restricted_id=setting("restricted_role_id","")
            threshold=setting("raid_join_threshold","6")
            try: threshold=max(3,min(30,int(threshold)))
            except ValueError: threshold=6
            last_join=now.isoformat()
            set_setting("raid_last_join_at",last_join)
            raid=len(self.joins)>=threshold
            lock_raw=setting("raid_lockdown_until","")
            try: lockdown_active=bool(lock_raw and datetime.fromisoformat(lock_raw)>now)
            except ValueError: lockdown_active=False
            if raid:
                set_setting("raid_lockdown_until",(now+timedelta(minutes=30)).isoformat())
                db.session.add(AuditLog(actor_discord_id="kaplumbik",action="security.raid_lockdown",target_type="guild",target_id=str(member.guild.id),details={"join_count":len(self.joins),"window_seconds":30},success=True)); db.session.commit()
        try:
            if (raid or lockdown_active) and restricted_id.isdigit():
                role=member.guild.get_role(int(restricted_id))
                if role: await member.add_roles(role,reason="Kaplumbik anti-raid temporary restriction")
            if unverified_id.isdigit():
                role=member.guild.get_role(int(unverified_id))
                if role: await member.add_roles(role,reason="Kaplumbik verification required")
            if verify_channel_id.isdigit():
                channel=self.bot.get_channel(int(verify_channel_id))
                if channel is None:
                    try: channel=await self.bot.fetch_channel(int(verify_channel_id))
                    except discord.HTTPException: channel=None
                if channel: await channel.send(f"{member.mention}, Mahzen'e hoş geldin! Kuralları okuyup doğrulama düğmesine bas.",view=VerificationView(),allowed_mentions=discord.AllowedMentions(users=[member]))
        except discord.HTTPException:
            log.exception("Member join security flow failed for %s",member.id)
        if raid:
            await self.alert_owner(f"🚨 Mahzen anti-raid kilidi açıldı: 30 saniyede {len(self.joins)} yeni üye. Yeni üyeler varsa kısıtlı role alınır. Kilidi yalnızca sen, son katılımdan 30 dakika geçtikten sonra kaldırabilirsin.")


    async def _handle_nuke_event(self,guild,action,target_id):
        now=datetime.now(timezone.utc)
        while self.deletions and (now-self.deletions[0][0]).total_seconds()>60: self.deletions.popleft()
        self.deletions.append((now,action,str(target_id)))
        app=create_app()
        with app.app_context():
            set_setting("nuke_last_delete_at",now.isoformat())
            raw=setting("nuke_lockdown_until","")
            try: active=bool(raw and datetime.fromisoformat(raw)>now)
            except ValueError: active=False
            triggered=len(self.deletions)>=3 and not active
            if triggered:
                set_setting("nuke_lockdown_until",(now+timedelta(minutes=30)).isoformat())
                db.session.add(AuditLog(actor_discord_id="kaplumbik",action="security.anti_nuke_alert",target_type="guild",target_id=str(guild.id),details={"deletions_last_minute":len(self.deletions),"last_action":action},success=True)); db.session.commit()
        if not triggered: return
        await asyncio.sleep(1)
        audit_action=discord.AuditLogAction.channel_delete if action=="channel_delete" else discord.AuditLogAction.role_delete
        actor=None
        try:
            async for entry in guild.audit_logs(limit=8,action=audit_action):
                if getattr(entry.target,"id",None)==int(target_id) and (now-entry.created_at.astimezone(timezone.utc)).total_seconds()<20:
                    actor=entry.user; break
        except discord.Forbidden:
            log.warning("Missing View Audit Log permission for anti-nuke actor identification.")
        if actor and not actor.bot and not actor.guild_permissions.administrator and str(actor.id)!=str(settings.owner_discord_id):
            app=create_app()
            with app.app_context(): restricted_id=setting("restricted_role_id","")
            role=guild.get_role(int(restricted_id)) if restricted_id.isdigit() else None
            member=guild.get_member(actor.id)
            if role and member:
                try: await member.add_roles(role,reason="Kaplumbik anti-nuke restriction; owner review required")
                except discord.HTTPException: log.exception("Could not restrict suspected nuke actor.")
        await self.alert_owner(f"🚨 Anti-nuke uyarısı: 60 saniyede {len(self.deletions)} rol/kanal silme olayı görüldü. Son işlem: {action} · hedef ID {target_id}. Şüpheli aktör: {actor} ({getattr(actor,'id','bilinmiyor')}). Kontrol etmeden kilidi kaldırma.")

    @commands.Cog.listener()
    async def on_guild_channel_delete(self,channel):
        await self._handle_nuke_event(channel.guild,"channel_delete",channel.id)

    @commands.Cog.listener()
    async def on_guild_role_delete(self,role):
        await self._handle_nuke_event(role.guild,"role_delete",role.id)

    @commands.Cog.listener()
    async def on_message(self,message):
        if not message.guild or message.author.bot or message.webhook_id: return
        if not (message.mention_everyone or "@everyone" in message.content or "@here" in message.content): return
        member=message.author
        if not isinstance(member,discord.Member): return
        if member.guild_permissions.administrator or (settings.owner_discord_id and str(member.id)==str(settings.owner_discord_id)): return
        try:
            await message.delete()
            app=create_app()
            with app.app_context():
                db.session.add(AuditLog(actor_discord_id=str(member.id),action="security.mass_mention_blocked",target_type="message",target_id=str(message.id),details={"channel_id":str(message.channel.id)},success=True)); db.session.commit()
            try: await member.send(f"Mahzen'de @everyone/@here kullanma iznin olmadığı için mesajın kaldırıldı. Kanal: #{getattr(message.channel,'name','kanal')}.")
            except discord.HTTPException: pass
        except discord.HTTPException:
            log.exception("Could not remove unauthorized mass mention.")

    @tasks.loop(minutes=30)
    async def unverified_watch(self):
        await self.bot.wait_until_ready()
        app=create_app()
        with app.app_context():
            role_id=setting("unverified_role_id","")
            if not role_id.isdigit(): return
            role_id=int(role_id)
            guild_ids=[int(x) for x in setting("security_guild_ids","").split(",") if x.strip().isdigit()]
            if not guild_ids: guild_ids=[g.id for g in self.bot.guilds]
            pending=[]
            for guild_id in guild_ids:
                guild=self.bot.get_guild(guild_id)
                if not guild: continue
                role=guild.get_role(role_id)
                if not role: continue
                for member in role.members:
                    if member.joined_at and (datetime.now(timezone.utc)-member.joined_at.astimezone(timezone.utc))>=timedelta(hours=24):
                        key=f"unverified_alert:{member.guild.id}:{member.id}"
                        if setting(key,"")!="sent":
                            set_setting(key,"sent")
                            pending.append((member.guild.name,member.id))
        if pending:
            app=create_app()
            with app.app_context(): alert_channel_id=setting("security_alert_channel_id","")
            alert_channel=self.bot.get_channel(int(alert_channel_id)) if alert_channel_id.isdigit() else None
            if alert_channel:
                body="⏰ **24 saati geçen doğrulanmamış üyeler**\n"+"\n".join(f"• {guild_name} · Discord ID {member_id}" for guild_name,member_id in pending[:20])
                try: await alert_channel.send(body[:1900],allowed_mentions=discord.AllowedMentions.none())
                except discord.HTTPException: log.exception("Could not post unverified member alerts to channel.")
        for guild_name,member_id in pending:
            await self.alert_owner(f"⏰ Doğrulanmamış üye 24 saati geçti: {guild_name} · Discord ID {member_id}.")

    @unverified_watch.before_loop
    async def before_unverified_watch(self):
        await self.bot.wait_until_ready()


    @app_commands.command(name="denetimlogu",description="Son güvenlik ve yönetim denetim kayıtlarını göster (yönetici).")
    async def audit_history(self,interaction:discord.Interaction):
        if not admin(interaction):
            await interaction.response.send_message("Denetim kayıtları yalnızca sunucu sahibi veya Administrator yetkilisine açık.",ephemeral=True); return
        app=create_app()
        with app.app_context():
            rows=db.session.execute(select(AuditLog).order_by(AuditLog.created_at.desc()).limit(12)).scalars().all()
            snapshot=[(row.action,row.actor_discord_id,row.target_type,row.target_id,row.created_at,row.success) for row in rows]
        lines=[]
        for action,actor,target_type,target_id,created,success in snapshot:
            if created.tzinfo is None: created=created.replace(tzinfo=timezone.utc)
            lines.append(f"{'OK' if success else 'HATA'} · {action} · yetkili {actor or 'sistem'} · {target_type or '-'}:{target_id or '-'} · <t:{int(created.timestamp())}:R>")
        await interaction.response.send_message("Son denetim kayıtları\n"+("\n".join(lines) if lines else "Henüz kayıt yok."),ephemeral=True)

    @app_commands.command(name="davet",description="Yönetici tarafından sınırlı süreli sunucu daveti oluştur.")
    async def create_invite(self,interaction:discord.Interaction,kanal:discord.TextChannel,sure_saat:app_commands.Range[int,1,168]=24,kullanim:app_commands.Range[int,1,100]=10):
        if not admin(interaction):
            await interaction.response.send_message("Davet oluşturmak yalnızca sunucu sahibi veya Administrator yetkilisine açık.",ephemeral=True); return
        permissions=kanal.permissions_for(interaction.guild.me) if interaction.guild and interaction.guild.me else None
        if permissions is None or not permissions.create_instant_invite:
            await interaction.response.send_message("Botun bu kanalda Davet Oluştur izni yok.",ephemeral=True); return
        try:
            invite=await kanal.create_invite(max_age=int(sure_saat)*3600,max_uses=int(kullanim),unique=True,reason=f"Kaplumbik invite requested by {interaction.user}")
            app=create_app()
            with app.app_context():
                db.session.add(AuditLog(actor_discord_id=str(interaction.user.id),action="security.invite_created",target_type="channel",target_id=str(kanal.id),details={"max_age_hours":int(sure_saat),"max_uses":int(kullanim)},success=True)); db.session.commit()
            await interaction.response.send_message(f"Sınırlı davet oluşturuldu: {invite.url}\nSüre: {sure_saat} saat · kullanım: {kullanim}.",ephemeral=True)
        except discord.HTTPException:
            await interaction.response.send_message("Davet oluşturulamadı. Botun kanal izinlerini kontrol et.",ephemeral=True)

    @app_commands.command(name="guvenlikrolleri",description="Doğrulama, üye, kısıtlı ve yardımcı rollerini ayarla (yalnızca sahip).")
    async def configure_roles(self,interaction:discord.Interaction,dogrulanmamis:discord.Role,uye:discord.Role,kisitli:discord.Role,yardimci:discord.Role,kanal:discord.TextChannel,uyari_kanali:discord.TextChannel|None=None):
        if not owner(interaction):
            await interaction.response.send_message("Bu güvenlik yapılandırması yalnızca sunucu sahibine açık.",ephemeral=True); return
        if interaction.guild and interaction.guild.me:
            for role in (dogrulanmamis,uye,kisitli):
                if role>=interaction.guild.me.top_role:
                    await interaction.response.send_message("Botun rolü, ayarlanan rollerin üstünde olmalı.",ephemeral=True); return
        app=create_app()
        with app.app_context():
            set_setting("unverified_role_id",str(dogrulanmamis.id),interaction.user.id)
            set_setting("member_role_id",str(uye.id),interaction.user.id)
            set_setting("restricted_role_id",str(kisitli.id),interaction.user.id)
            set_setting("helper_role_id",str(yardimci.id),interaction.user.id)
            set_setting("verification_channel_id",str(kanal.id),interaction.user.id)
            if uyari_kanali: set_setting("security_alert_channel_id",str(uyari_kanali.id),interaction.user.id)
            set_setting("security_guild_ids",str(interaction.guild_id),interaction.user.id)
        await interaction.response.send_message("Doğrulama ve güvenlik rolleri kaydedildi. Botun Rol Yönetimi izni ve rol hiyerarşisini doğrula.",ephemeral=True)

    @app_commands.command(name="raidkilidikaldir",description="Anti-raid kilidini kaldır (yalnızca sahip; son katılımdan 30 dakika geçmeli).")
    async def unlock_raid(self,interaction:discord.Interaction):
        if not owner(interaction):
            await interaction.response.send_message("Anti-raid kilidini yalnızca sunucu sahibi kaldırabilir.",ephemeral=True); return
        app=create_app()
        with app.app_context():
            raw_values=[setting("raid_last_join_at",""),setting("nuke_last_delete_at","")]
            latest=[]
            for raw in raw_values:
                try:
                    parsed=datetime.fromisoformat(raw) if raw else None
                    if parsed and parsed.tzinfo is None: parsed=parsed.replace(tzinfo=timezone.utc)
                    if parsed: latest.append(parsed)
                except ValueError: pass
            last=max(latest) if latest else None
            if last and datetime.now(timezone.utc)-last<timedelta(minutes=30):
                remaining=timedelta(minutes=30)-(datetime.now(timezone.utc)-last)
                await interaction.response.send_message(f"Son raid/nuke belirtisinden sonra 30 dakika dolmadı. Yaklaşık {max(1,int(remaining.total_seconds()/60))} dakika daha bekle.",ephemeral=True); return
            set_setting("raid_lockdown_until","",interaction.user.id)
            set_setting("nuke_lockdown_until","",interaction.user.id)
            db.session.add(AuditLog(actor_discord_id=str(interaction.user.id),action="security.raid_unlocked",target_type="guild",target_id=str(interaction.guild_id),details={},success=True)); db.session.commit()
        await interaction.response.send_message("Anti-raid kilidi kaldırıldı. Güvenlik kaydı oluşturuldu.",ephemeral=True)

    @app_commands.command(name="uyetimeout",description="Üyeye süreli zaman aşımı uygula; Yardımcı en fazla 10 dakika.")
    async def member_timeout(self,interaction:discord.Interaction,uye:discord.Member,dakika:app_commands.Range[int,1,40320],gerekce:app_commands.Range[str,3,300]):
        helper_id=""
        app=create_app()
        with app.app_context(): helper_id=setting("helper_role_id","")
        is_helper=isinstance(interaction.user,discord.Member) and helper_id.isdigit() and any(str(r.id)==helper_id for r in interaction.user.roles)
        is_admin_user=admin(interaction)
        if not is_admin_user and not is_helper:
            await interaction.response.send_message("Bu işlem Yardımcı, Administrator veya sunucu sahibi gerektirir.",ephemeral=True); return
        if is_helper and not is_admin_user and dakika>10:
            await interaction.response.send_message("Yardımcı rolü en fazla 10 dakikalık timeout uygulayabilir; daha uzun süre için Administrator gerekir.",ephemeral=True); return
        if uye.guild_permissions.administrator or (settings.owner_discord_id and str(uye.id)==str(settings.owner_discord_id)):
            await interaction.response.send_message("Yönetici veya sunucu sahibi bu komutla timeout edilemez.",ephemeral=True); return
        try:
            await uye.timeout(timedelta(minutes=int(dakika)),reason=f"{interaction.user} · {gerekce[:300]}")
            app=create_app()
            with app.app_context():
                db.session.add(AuditLog(actor_discord_id=str(interaction.user.id),action="moderation.timeout",target_type="member",target_id=str(uye.id),details={"minutes":int(dakika),"reason":gerekce[:300]},success=True)); db.session.commit()
            await interaction.response.send_message(f"{uye.mention} için {dakika} dakikalık timeout uygulandı.",allowed_mentions=discord.AllowedMentions.none())
        except discord.HTTPException:
            await interaction.response.send_message("Timeout uygulanamadı. Botun Moderasyon Üyelerini Zaman Aşımına Uğrat iznini ve rol sırasını kontrol edin.",ephemeral=True)

async def setup(bot):
    await bot.add_cog(SecurityCog(bot))

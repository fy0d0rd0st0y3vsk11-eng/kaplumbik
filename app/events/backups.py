import gzip
import io
import json
import logging
import os
from datetime import date, datetime, timezone, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from discord.ext import commands, tasks
from sqlalchemy import select
from cryptography.fernet import Fernet

from app import create_app
from app.core.config import settings
from app.database import db
from app.database.advanced_models import BotSetting, BotHealthRecord
from app.database.models import AuditLog

log=logging.getLogger("kaplumbik.backups")
TR=ZoneInfo("Europe/Istanbul")
RETENTION_DAYS=30

def _encode(value):
    if isinstance(value,datetime): return {"__type__":"datetime","value":value.isoformat()}
    if isinstance(value,date): return {"__type__":"date","value":value.isoformat()}
    if isinstance(value,bytes): return {"__type__":"bytes","value":value.hex()}
    if isinstance(value,(list,tuple)): return [_encode(x) for x in value]
    if isinstance(value,dict): return {str(k):_encode(v) for k,v in value.items()}
    if value is None or isinstance(value,(str,int,float,bool)): return value
    return str(value)

def _decode(value,column):
    if isinstance(value,dict) and value.get("__type__")=="datetime": return datetime.fromisoformat(value["value"])
    if isinstance(value,dict) and value.get("__type__")=="date": return date.fromisoformat(value["value"])
    if isinstance(value,dict) and value.get("__type__")=="bytes": return bytes.fromhex(value["value"])
    if isinstance(value,dict): return {k:_decode(v,column) for k,v in value.items()}
    if isinstance(value,list): return [_decode(v,column) for v in value]
    return value

def _backup_dir():
    return Path(os.getenv("BACKUP_DIR", str(Path("instance")/"backups"))).expanduser()

def _s3_client():
    endpoint=os.getenv("BACKUP_S3_ENDPOINT","").strip()
    access=os.getenv("BACKUP_S3_ACCESS_KEY","").strip()
    secret=os.getenv("BACKUP_S3_SECRET_KEY","").strip()
    if not (endpoint and access and secret and os.getenv("BACKUP_S3_BUCKET","").strip()): return None
    import boto3
    return boto3.client("s3",endpoint_url=endpoint,aws_access_key_id=access,aws_secret_access_key=secret)

def create_backup():
    app=create_app()
    with app.app_context():
        metadata=db.metadata
        tables=[]
        for table in metadata.sorted_tables:
            rows=db.session.execute(select(table)).mappings().all()
            tables.append({"name":table.name,"rows":[{key:_encode(value) for key,value in row.items()} for row in rows]})
        payload={"format_version":1,"created_at":datetime.now(timezone.utc).isoformat(),"database_dialect":db.engine.dialect.name,"tables":tables}
        day=datetime.now(TR).strftime("%Y-%m-%d")
        filename=f"kaplumbik-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json.gz"
        directory=_backup_dir(); directory.mkdir(parents=True,exist_ok=True)
        key=os.getenv("BACKUP_ENCRYPTION_KEY","").strip()
        if settings.app_env.casefold()=="production" and not key:
            raise RuntimeError("Production backups require BACKUP_ENCRYPTION_KEY.")
        compressed=gzip.compress(json.dumps(payload,ensure_ascii=False,separators=(",",":")).encode("utf-8"))
        if key:
            compressed=Fernet(key.encode("ascii")).encrypt(compressed)
            filename += ".enc"
        path=directory/filename
        path.write_bytes(compressed)
        bucket=os.getenv("BACKUP_S3_BUCKET","").strip()
        client=_s3_client()
        remote=False
        if client and bucket:
            client.upload_file(str(path),bucket,filename)
            remote=True
            cutoff=datetime.now(timezone.utc)-timedelta(days=RETENTION_DAYS)
            response=client.list_objects_v2(Bucket=bucket)
            for item in response.get("Contents",[]):
                if item["Key"].startswith("kaplumbik-") and item["LastModified"]<cutoff: client.delete_object(Bucket=bucket,Key=item["Key"])
        cutoff_local=datetime.now(timezone.utc)-timedelta(days=RETENTION_DAYS)
        for old in directory.glob("kaplumbik-*.json.gz"):
            try:
                if datetime.fromtimestamp(old.stat().st_mtime,timezone.utc)<cutoff_local: old.unlink()
            except OSError: log.exception("Could not prune old backup %s",old)
        setting=db.session.get(BotSetting,"backup_last_success")
        if setting is None: setting=BotSetting(key="backup_last_success",value=datetime.now(timezone.utc).isoformat()); db.session.add(setting)
        else: setting.value=datetime.now(timezone.utc).isoformat()
        setting.updated_by="kaplumbik"
        db.session.add(BotHealthRecord(component="database_backup",status="ok",details=f"Created {filename}; remote_s3={remote}"))
        db.session.add(AuditLog(actor_discord_id="kaplumbik",action="backup.created",target_type="database_backup",target_id=filename,details={"remote_s3":remote,"retention_days":RETENTION_DAYS},success=True))
        db.session.commit()
        return str(path),remote

def restore_backup(path):
    """Destructive restore helper. Caller must explicitly confirm before invoking."""
    source=Path(path)
    raw=source.read_bytes()
    if source.suffix==".enc":
        key=os.getenv("BACKUP_ENCRYPTION_KEY","").strip()
        if not key: raise ValueError("BACKUP_ENCRYPTION_KEY is required to decrypt this backup.")
        raw=Fernet(key.encode("ascii")).decrypt(raw)
    if raw[:2]==b"\\x1f\\x8b": raw=gzip.decompress(raw)
    payload=json.loads(raw.decode("utf-8"))
    if payload.get("format_version")!=1 or not isinstance(payload.get("tables"),list): raise ValueError("Unsupported or invalid backup format.")
    app=create_app()
    with app.app_context():
        table_map={table.name:table for table in db.metadata.sorted_tables}
        incoming={item.get("name"):item.get("rows",[]) for item in payload["tables"]}
        if any(name not in table_map for name in incoming): raise ValueError("Backup contains unknown tables.")
        with db.engine.begin() as connection:
            for table in reversed(db.metadata.sorted_tables):
                if table.name in incoming: connection.execute(table.delete())
            for table in db.metadata.sorted_tables:
                for row in incoming.get(table.name,[]):
                    values={}
                    for column in table.columns:
                        if column.name in row: values[column.name]=_decode(row[column.name],column)
                    connection.execute(table.insert().values(**values))
    return len(payload["tables"])

class BackupCog(commands.Cog):
    def __init__(self,bot): self.bot=bot
    async def cog_load(self):
        if not self.daily_backup.is_running(): self.daily_backup.start()
    def cog_unload(self): self.daily_backup.cancel()

    async def alert_owner(self,message):
        if not settings.owner_discord_id or not settings.owner_discord_id.isdigit(): return
        try:
            user=self.bot.get_user(int(settings.owner_discord_id)) or await self.bot.fetch_user(int(settings.owner_discord_id))
            await user.send(message[:1800])
        except discord.HTTPException: log.exception("Backup alert DM failed")

    @tasks.loop(minutes=30)
    async def daily_backup(self):
        await self.bot.wait_until_ready()
        app=create_app()
        with app.app_context():
            row=db.session.get(BotSetting,"backup_last_success")
            last=row.value if row else ""
        today=datetime.now(TR).date().isoformat()
        if last:
            try:
                if datetime.fromisoformat(last).astimezone(TR).date().isoformat()==today: return
            except ValueError: pass
        try:
            path,remote=await __import__("asyncio").to_thread(create_backup)
            if not remote:
                log.warning("Database backup is local only. Configure BACKUP_S3_* or a persistent BACKUP_DIR for durable backups on Render.")
        except Exception:
            log.exception("Daily database backup failed")
            app=create_app()
            with app.app_context():
                db.session.add(BotHealthRecord(component="database_backup",status="error",details="Daily backup failed; see service logs"))
                db.session.commit()
            await self.alert_owner("🚨 Kaplumbik günlük veri tabanı yedeği başarısız oldu. Render günlüklerini ve yedekleme ayarlarını kontrol et.")

    @daily_backup.before_loop
    async def before_daily_backup(self): await self.bot.wait_until_ready()

    @app_commands.command(name="yedekle",description="Veri tabanının anlık yedeğini oluştur (yalnızca sahip).")
    async def manual_backup(self,interaction:discord.Interaction):
        if not settings.owner_discord_id or str(interaction.user.id)!=str(settings.owner_discord_id):
            await interaction.response.send_message("Yedekleme yalnızca sunucu sahibine açık.",ephemeral=True); return
        await interaction.response.defer(ephemeral=True,thinking=True)
        try:
            path,remote=await __import__("asyncio").to_thread(create_backup)
            await interaction.followup.send("Yedek oluşturuldu. "+("Uzak depoya da yüklendi." if remote else "Yalnızca yerel diske yazıldı; Render'da kalıcı değildir, S3 uyumlu depolama yapılandırılmalı."),ephemeral=True)
        except Exception:
            log.exception("Manual backup failed")
            await interaction.followup.send("Yedekleme başarısız oldu. Hata kayıtlarını kontrol et.",ephemeral=True)

    @app_commands.command(name="yedekdurum",description="Son yedekleme durumunu göster (yalnızca sahip).")
    async def backup_status(self,interaction:discord.Interaction):
        if not settings.owner_discord_id or str(interaction.user.id)!=str(settings.owner_discord_id):
            await interaction.response.send_message("Bu bilgi yalnızca sunucu sahibine açık.",ephemeral=True); return
        app=create_app()
        with app.app_context():
            row=db.session.get(BotSetting,"backup_last_success")
            health=db.session.execute(select(BotHealthRecord).where(BotHealthRecord.component=="database_backup").order_by(BotHealthRecord.checked_at.desc()).limit(1)).scalar_one_or_none()
            last=row.value if row else "Henüz yedek yok"
            detail=health.details if health else "Durum kaydı yok"
        await interaction.response.send_message(f"Son başarılı yedek: {last}\nDurum: {detail}\nYerel yedek klasörü: {_backup_dir()}\nS3 bucket: {'yapılandırıldı' if os.getenv('BACKUP_S3_BUCKET') else 'yapılandırılmadı'}",ephemeral=True)

async def setup(bot): await bot.add_cog(BackupCog(bot))

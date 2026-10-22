from app import create_app
from app.database import db
from app.database.models import UserProfile
from app.events.backups import create_backup, restore_backup

def test_backup_restore_round_trip_on_isolated_database(tmp_path, monkeypatch):
    monkeypatch.setenv("BACKUP_DIR", str(tmp_path))
    application=create_app({"TESTING":True,"SECRET_KEY":"test-only-secret","SQLALCHEMY_DATABASE_URI":"sqlite://"})
    with application.app_context():
        db.create_all()
        db.session.add(UserProfile(discord_id="12345678901234567",username="Backup test",balance=42))
        db.session.commit()
        path,_=create_backup(application)
        profile=UserProfile.query.filter_by(discord_id="12345678901234567").one()
        profile.balance=999
        db.session.commit()
        restore_backup(path,application)
        db.session.expire_all()
        restored=UserProfile.query.filter_by(discord_id="12345678901234567").one()
        assert restored.balance==42
        db.session.remove()

def test_encrypted_local_backups_obey_30_day_retention(tmp_path, monkeypatch):
    import os
    from datetime import datetime, timedelta, timezone
    from cryptography.fernet import Fernet
    monkeypatch.setenv("BACKUP_DIR", str(tmp_path))
    monkeypatch.setenv("BACKUP_ENCRYPTION_KEY", Fernet.generate_key().decode("ascii"))
    old=tmp_path/"kaplumbik-old.json.gz.enc"
    old.write_bytes(b"expired")
    timestamp=(datetime.now(timezone.utc)-timedelta(days=31)).timestamp()
    os.utime(old,(timestamp,timestamp))
    application=create_app({"TESTING":True,"SECRET_KEY":"test-only-secret","SQLALCHEMY_DATABASE_URI":"sqlite://"})
    with application.app_context():
        db.create_all()
        create_backup(application)
    assert not old.exists()

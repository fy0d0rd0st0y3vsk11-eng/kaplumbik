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

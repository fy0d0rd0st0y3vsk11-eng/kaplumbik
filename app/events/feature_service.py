from sqlalchemy import select

from app.database import db
from app.database.advanced_models import AchievementDefinition, BotHealthRecord, BotSetting
from app.database.event_models import Event, EventParticipation

DEFAULT_SETTINGS = {
    "ai_personality": "Sen Kaplumbik'sin; Mahzen'in eğlenceli, sıcak ve hazırcevap maskotusun. Samimi ol ama yapmacık davranma; esprileri doğal ve dozunda kullan. Kullanıcının ruh hâline uyum sağla, ciddi konularda ciddileş. Türkçe konuş; kullanıcı başka dilde yazarsa o dilde cevap ver. Bilmediğin bilgiyi uydurma, gereksiz uzatma ve her mesaja emoji ekleme.",
    "game_announcement_channel_id": "",
    "announcement_channel_id": "",
    "announcements_per_day": "3",
    "announcement_everyone_ping": "true",
    "game_reminder_minutes": "15,5",
    "minecraft_realms_link": "",
    "gartic_phone_link": "",
    "among_us_room_code": "",
    "designer_discord_id": "",
    "new_member_intro": "Mahzen'e hoş geldin! Etkinliklere katılabilir, insanlarla tanışabilir ve oyunlardan puan kazanabilirsin.",
    "server_knowledge": "Kaplumbik, Mahzen sunucusunun sohbet eden yardımcı botudur. Üyelere kayıtlı kişi tanıtımlarını ve yönetim paneline eklenen sunucu bilgilerini aktarır; etkinlik/hatırlatma metinlerini yöneticinin yazdığı şekilde gönderir.",
    "daily_announcement_text": "🎮 Mahzen oyun hatırlatması! Bugün oyuna katılmak istiyorsan etkinliklere göz at ve katılımını bildir: /etkinlikler",
    "giveaway_min_points": "100",
}


def get_setting(key, default=""):
    row = db.session.get(BotSetting, key)
    if row:
        return row.value
    return DEFAULT_SETTINGS.get(key, default)


def set_setting(key, value, actor_discord_id=None):
    if not key or len(key) > 100 or len(value) > 8000:
        raise ValueError("Ayar adı veya değeri geçersiz.")
    row = db.session.get(BotSetting, key)
    if row is None:
        row = BotSetting(key=key, value=value)
        db.session.add(row)
    else:
        row.value = value
    row.updated_by = str(actor_discord_id) if actor_discord_id else None
    db.session.commit()
    return row


def get_rsvp_summary(event_id):
    event = db.session.get(Event, event_id)
    if event is None:
        raise ValueError("Etkinlik bulunamadı.")
    rows = db.session.execute(select(EventParticipation).where(EventParticipation.event_id == event_id)).scalars().all()
    return {
        "event_id": event_id,
        "going": [r.discord_id for r in rows if r.status == "going"],
        "not_going": [r.discord_id for r in rows if r.status == "not_going"],
        "attended": [r.discord_id for r in rows if r.status == "attended"],
        "absent": [r.discord_id for r in rows if r.status == "absent"],
    }


def seed_achievements():
    defaults = [
        ("first_game", "İlk Oyun", "İlk etkinliğine katıl.", "events_attended", 1),
        ("regular", "Düzenli Oyuncu", "5 etkinliğe katıl.", "events_attended", 5),
        ("multiplayer", "Takım Oyuncusu", "3 farklı oyunda etkinliğe katıl.", "unique_games", 3),
        ("comeback", "Geri Döndü", "Uzun bir aradan sonra tekrar katıl.", "comeback_days", 30),
        ("event_master", "Etkinlik Ustası", "20 etkinliğe katıl.", "events_attended", 20),
    ]
    for key, title, description, condition_type, threshold in defaults:
        row = db.session.execute(select(AchievementDefinition).where(AchievementDefinition.key == key)).scalar_one_or_none()
        if row is None:
            db.session.add(AchievementDefinition(key=key, title=title, description=description, condition_type=condition_type, threshold=threshold))
    db.session.commit()


def record_health(component, status, details=""):
    db.session.add(BotHealthRecord(component=component[:60], status=status[:20], details=details[:500] or None))
    db.session.commit()


def health_snapshot(limit=30):
    return list(db.session.execute(select(BotHealthRecord).order_by(BotHealthRecord.checked_at.desc()).limit(max(1, min(limit, 100)))).scalars())

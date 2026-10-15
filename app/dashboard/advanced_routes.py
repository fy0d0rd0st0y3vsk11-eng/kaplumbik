import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from flask import flash, redirect, render_template_string, request, session, url_for

from app.database import db
from app.database.advanced_models import AchievementDefinition, AnnouncementLog
from app.database.event_models import Event
from app.database.models import AuditLog
from app.events.feature_service import get_setting, set_setting, health_snapshot, seed_achievements
from app.dashboard import dashboard_bp
from app.dashboard.routes import owner_required, _require_csrf

logger = logging.getLogger("kaplumbik.dashboard.advanced")

SETTINGS_PAGE = """
<!doctype html><html lang="tr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Kaplumbik gelişmiş ayarlar</title>
<style>body{font:15px system-ui;background:#101117;color:#f4f4f8;max-width:1000px;margin:25px auto;padding:0 16px}section{background:#191b25;border:1px solid #303342;border-radius:14px;padding:18px;margin:16px 0}label{display:block;color:#aaa;margin-top:10px}input,textarea,select{width:100%;padding:10px;background:#101117;color:#fff;border:1px solid #45465a;border-radius:8px}textarea{min-height:80px}button,a{display:inline-block;margin-top:12px;padding:10px 14px;background:#a78bfa;color:#171322;border:0;border-radius:8px;font-weight:bold}a{color:#171322;text-decoration:none}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:12px}.muted{color:#aaa}table{width:100%;border-collapse:collapse}td,th{text-align:left;padding:8px;border-bottom:1px solid #333}</style></head><body>
<h1>🐢 Kaplumbik · Gelişmiş yönetim</h1><p class="muted">Bu sayfadaki ayarlar veritabanında saklanır. API anahtarlarını buraya yazma; gizli anahtarlar ortam değişkeni olarak tutulmalı.</p>
<a href="{{ url_for('dashboard.index') }}">← Ana panele dön</a>
<form method="post" action="{{ url_for('dashboard.advanced_save') }}"><input type="hidden" name="csrf_token" value="{{ csrf_token }}">
<section><h2>AI kişiliği ve tanıtım</h2><label>AI kişilik talimatı</label><textarea name="ai_personality" maxlength="6000">{{ values.ai_personality }}</textarea><label>Yeni üye tanıtım metni</label><textarea name="new_member_intro" maxlength="3000">{{ values.new_member_intro }}</textarea><label>Tasarımcı Discord kullanıcı ID'si</label><input name="designer_discord_id" pattern="[0-9]{15,25}" value="{{ values.designer_discord_id }}"><label>Çekiliş için gereken minimum puan</label><input name="giveaway_min_points" type="number" min="0" max="10000000" value="{{ values.giveaway_min_points }}"></section>
<section><h2>Oyun bağlantıları</h2><label>Minecraft Realms bağlantısı</label><input name="minecraft_realms_link" type="url" maxlength="500" value="{{ values.minecraft_realms_link }}"><label>Gartic Phone bağlantısı</label><input name="gartic_phone_link" type="url" maxlength="500" value="{{ values.gartic_phone_link }}"><label>Among Us oda kodu</label><input name="among_us_room_code" maxlength="100" value="{{ values.among_us_room_code }}"></section>
<section><h2>Duyuru ve hatırlatmalar</h2><label>Duyuru kanalı ID'si</label><input name="announcement_channel_id" pattern="[0-9]{15,25}" value="{{ values.announcement_channel_id }}"><label>Etkinlik duyuru kanalı ID'si (boşsa üstteki kullanılır)</label><input name="game_announcement_channel_id" pattern="[0-9]{0,25}" value="{{ values.game_announcement_channel_id }}"><label>Günlük genel duyuru saatleri (Türkiye saati, virgülle; ör. 12:00,17:00,20:00)</label><input name="announcement_times" value="{{ values.announcement_times }}"><label>Başlangıçtan önce hatırlatma dakikaları (virgülle; ör. 15,5)</label><input name="game_reminder_minutes" value="{{ values.game_reminder_minutes }}"><label>Her duyuruda @everyone kullanılsın mı?</label><select name="announcement_everyone_ping"><option value="true" {% if values.announcement_everyone_ping == 'true' %}selected{% endif %}>Evet</option><option value="false" {% if values.announcement_everyone_ping != 'true' %}selected{% endif %}>Hayır</option></select><button type="submit">Ayarları kaydet</button></section></form>
<section><h2>Başarımlar</h2><p class="muted">Koşullar düzenlenebilir. Bu sürümde tanım/koşul kaydı vardır; profil kartlarına otomatik rozet dağıtımı ayrı kontrol gerektirir.</p>
{% for item in achievements %}<form method="post" action="{{ url_for('dashboard.achievement_save', achievement_id=item.id) }}"><input type="hidden" name="csrf_token" value="{{ csrf_token }}"><strong>{{ item.key }}</strong><div class="grid"><div><label>Başlık</label><input name="title" maxlength="100" value="{{ item.title }}" required></div><div><label>Koşul türü</label><select name="condition_type">{% for kind in ['events_attended','unique_games','comeback_days','points'] %}<option value="{{ kind }}" {% if item.condition_type == kind %}selected{% endif %}>{{ kind }}</option>{% endfor %}</select></div><div><label>Eşik</label><input name="threshold" type="number" min="1" max="100000" value="{{ item.threshold }}" required></div></div><label>Açıklama</label><input name="description" maxlength="300" value="{{ item.description }}"><label><input style="width:auto" type="checkbox" name="enabled" {% if item.enabled %}checked{% endif %}> Etkin</label><button type="submit">Başarımı kaydet</button></form>{% endfor %}</section>
<section><h2>İptal edilmiş etkinlikler</h2><p class="muted">Gelecekteki etkinlikler buradan geri alınabilir; geçmiş etkinlikler yeniden planlanmaz.</p>{% for event in cancelled_events %}<form method="post" action="{{ url_for('dashboard.restore_event', event_id=event.id) }}"><input type="hidden" name="csrf_token" value="{{ csrf_token }}"><strong>#{{ event.id }} · {{ event.title }}</strong> — {{ event.starts_at.strftime('%d.%m.%Y %H:%M') }}<button type="submit">Etkinliği geri yükle</button></form>{% else %}<p>Geri yüklenecek iptal edilmiş etkinlik yok.</p>{% endfor %}</section>
<section><h2>Son duyuru kayıtları</h2><table><tr><th>Etkinlik</th><th>Tür</th><th>Durum</th><th>Hata</th><th>Zaman</th></tr>{% for log in announcement_logs %}<tr><td>{{ log.event_id or 'Genel' }}</td><td>{{ log.kind }}</td><td>{{ 'Başarılı' if log.success else 'Hata' }}</td><td>{{ log.error or '' }}</td><td>{{ log.sent_at.strftime('%d.%m %H:%M:%S') }}</td></tr>{% else %}<tr><td colspan="5">Henüz duyuru kaydı yok.</td></tr>{% endfor %}</table></section>
<section><h2>Son sağlık kayıtları</h2><table><tr><th>Bileşen</th><th>Durum</th><th>Detay</th><th>Zaman</th></tr>{% for row in health %}<tr><td>{{ row.component }}</td><td>{{ row.status }}</td><td>{{ row.details or '' }}</td><td>{{ row.checked_at.strftime('%d.%m %H:%M:%S') }}</td></tr>{% else %}<tr><td colspan="4">Henüz sağlık kaydı yok.</td></tr>{% endfor %}</table></section>
</body></html>
"""

SETTING_KEYS = (
    "ai_personality", "new_member_intro", "designer_discord_id",
    "giveaway_min_points", "minecraft_realms_link", "gartic_phone_link",
    "among_us_room_code", "announcement_channel_id", "game_announcement_channel_id",
    "announcement_times", "game_reminder_minutes", "announcement_everyone_ping",
)


@dashboard_bp.get("/advanced")
@owner_required
def advanced_index():
    seed_achievements()
    values = {key: get_setting(key) for key in SETTING_KEYS}
    values["announcement_times"] = get_setting("announcement_times", "12:00,17:00,20:00")
    values["game_reminder_minutes"] = get_setting("game_reminder_minutes", "15,5")
    achievements = db.session.query(AchievementDefinition).order_by(AchievementDefinition.id).all()
    health = health_snapshot(30)
    announcement_logs = db.session.query(AnnouncementLog).order_by(AnnouncementLog.sent_at.desc()).limit(30).all()
    cancelled_events = db.session.query(Event).filter_by(status="cancelled").order_by(Event.starts_at.desc()).limit(30).all()
    return render_template_string(SETTINGS_PAGE, values=values, achievements=achievements, health=health, announcement_logs=announcement_logs, cancelled_events=cancelled_events, csrf_token=session.get("csrf_token", ""))


@dashboard_bp.post("/advanced/save")
@owner_required
def advanced_save():
    _require_csrf()
    actor = str(session["discord_id"])
    try:
        values = {key: request.form.get(key, "").strip() for key in SETTING_KEYS}
        for key in ("announcement_channel_id", "game_announcement_channel_id", "designer_discord_id"):
            value = values[key]
            if value and (not value.isdigit() or not 15 <= len(value) <= 25):
                raise ValueError(f"{key} için geçerli Discord ID gir.")
        minimum = int(values["giveaway_min_points"] or "100")
        if minimum < 0 or minimum > 10_000_000:
            raise ValueError("Çekiliş puan eşiği 0–10.000.000 arasında olmalı.")
        values["giveaway_min_points"] = str(minimum)
        times = [part.strip() for part in request.form.get("announcement_times", "12:00,17:00,20:00").split(",") if part.strip()]
        for item in times:
            datetime.strptime(item, "%H:%M")
        values["announcement_times"] = ",".join(times[:12])
        reminders = [int(part.strip()) for part in values["game_reminder_minutes"].split(",") if part.strip()]
        if any(n < 1 or n > 1440 for n in reminders):
            raise ValueError("Hatırlatma dakikaları 1–1440 aralığında olmalı.")
        values["game_reminder_minutes"] = ",".join(map(str, sorted(set(reminders), reverse=True)))
        for key, value in values.items():
            set_setting(key, value, actor)
        db.session.add(AuditLog(actor_discord_id=actor, action="settings.update", target_type="bot_settings", target_id="all", details={"keys": list(values)}, success=True))
        db.session.commit()
        flash("Gelişmiş ayarlar kaydedildi.")
    except Exception as exc:
        db.session.rollback()
        logger.exception("Could not save advanced settings")
        flash(f"Ayarlar kaydedilemedi: {str(exc)[:180]}")
    return redirect(url_for("dashboard.advanced_index"))


@dashboard_bp.post("/advanced/achievements/<int:achievement_id>")
@owner_required
def achievement_save(achievement_id):
    _require_csrf()
    item = db.session.get(AchievementDefinition, achievement_id)
    if item is None:
        flash("Başarım bulunamadı.")
        return redirect(url_for("dashboard.advanced_index"))
    try:
        item.title = request.form.get("title", "").strip()[:100]
        item.description = request.form.get("description", "").strip()[:300]
        item.condition_type = request.form.get("condition_type", "events_attended")
        if item.condition_type not in {"events_attended", "unique_games", "comeback_days", "points"}:
            raise ValueError("Koşul türü geçersiz.")
        item.threshold = int(request.form.get("threshold", "1"))
        if not item.title or not 1 <= item.threshold <= 100000:
            raise ValueError("Başlık ve 1–100.000 arası eşik gerekli.")
        item.enabled = request.form.get("enabled") == "on"
        db.session.add(AuditLog(actor_discord_id=str(session["discord_id"]), action="achievement.update", target_type="achievement", target_id=str(item.id), details={"key": item.key, "threshold": item.threshold}, success=True))
        db.session.commit()
        flash("Başarım koşulu kaydedildi.")
    except Exception as exc:
        db.session.rollback()
        logger.exception("Could not save achievement")
        flash(f"Başarım kaydedilemedi: {str(exc)[:180]}")
    return redirect(url_for("dashboard.advanced_index"))


@dashboard_bp.post("/advanced/events/<int:event_id>/restore")
@owner_required
def restore_event(event_id):
    _require_csrf()
    event = db.session.get(Event, event_id)
    try:
        if event is None or event.status != "cancelled":
            raise ValueError("Geri yüklenecek iptal edilmiş etkinlik bulunamadı.")
        event_start = event.starts_at
        if event_start.tzinfo is None:
            event_start = event_start.replace(tzinfo=timezone.utc)
        if event_start <= datetime.now(timezone.utc):
            raise ValueError("Geçmiş bir etkinlik yeniden planlanamaz.")
        event.status = "scheduled"
        db.session.add(AuditLog(actor_discord_id=str(session["discord_id"]), action="event.restore", target_type="event", target_id=str(event.id), details={"title": event.title}, success=True))
        db.session.commit()
        flash(f"Etkinlik #{event.id} geri yüklendi.")
    except Exception as exc:
        db.session.rollback()
        logger.exception("Could not restore event")
        flash(f"Etkinlik geri yüklenemedi: {str(exc)[:180]}")
    return redirect(url_for("dashboard.advanced_index"))

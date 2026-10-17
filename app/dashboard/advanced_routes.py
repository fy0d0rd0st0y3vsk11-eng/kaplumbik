import logging
import secrets
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from flask import flash, redirect, render_template_string, request, session, url_for

from app.database import db
from app.database.advanced_models import AchievementDefinition, AnnouncementLog, BotSetting, Giveaway, GiveawayParticipant, PersonProfile
from app.database.event_models import Event
from app.database.models import AuditLog, UserProfile
from app.events.feature_service import get_setting, set_setting, health_snapshot, seed_achievements
from app.dashboard import dashboard_bp
from app.dashboard.routes import owner_required, _require_csrf

logger = logging.getLogger("kaplumbik.dashboard.advanced")

SETTINGS_PAGE = """
<!doctype html><html lang="tr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Kaplumbik gelişmiş ayarlar</title>
<style>
:root{color-scheme:dark;--bg:#0b0c13;--panel:#151725;--line:#30354c;--accent:#b6a0ff;--mint:#9ee7d7;--text:#f5f3ff;--muted:#aaaec4}
*{box-sizing:border-box}body{font:15px/1.55 system-ui,-apple-system,sans-serif;background:radial-gradient(ellipse at 15% 0%,#292044 0,transparent 42%),radial-gradient(ellipse at 95% 12%,#153b3a 0,transparent 36%),var(--bg);color:var(--text);max-width:1120px;margin:26px auto;padding:0 16px 100px}
h1{font-size:clamp(26px,4vw,38px);letter-spacing:-.04em;margin:12px 0 4px}h2{font-size:19px;margin:0 0 10px}section{background:linear-gradient(145deg,rgba(27,30,48,.96),rgba(17,19,31,.96));border:1px solid var(--line);border-radius:20px;padding:clamp(16px,3vw,25px);margin:17px 0;box-shadow:0 12px 32px #0002}
label{display:block;color:#d1cde5;margin-top:12px;font-size:13px;font-weight:650}input,textarea,select{width:100%;padding:12px 13px;margin-top:5px;background:#0d0f19;color:var(--text);border:1px solid #3b3f59;border-radius:11px;font:inherit;outline:none}input:focus,textarea:focus,select:focus{border-color:var(--accent);box-shadow:0 0 0 3px #b6a0ff20}textarea{min-height:100px;resize:vertical}
button,.button,a.button{display:inline-flex;align-items:center;justify-content:center;gap:7px;margin-top:12px;padding:10px 15px;background:linear-gradient(110deg,var(--accent),#d2c6ff);color:#171322;border:0;border-radius:11px;font-weight:750;cursor:pointer;text-decoration:none}button:hover,.button:hover{filter:brightness(1.06);transform:translateY(-1px)}button.danger{background:#ffb7c4;color:#39101a}a{color:var(--mint)}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,280px),1fr));gap:14px}.muted{color:var(--muted)}.eyebrow{color:var(--mint);font-size:12px;text-transform:uppercase;letter-spacing:.14em;font-weight:800}.hero{padding:23px;border:1px solid #454061;border-radius:22px;background:linear-gradient(120deg,#2a2445cc,#152f32cc);margin:18px 0}.flash{padding:12px 15px;border:1px solid #6a5e93;background:#242039;border-radius:12px;margin:12px 0}.savebar{position:sticky;top:8px;z-index:5;padding:11px 14px;border-radius:14px;background:#151725ee;border:1px solid var(--line);backdrop-filter:blur(12px);display:flex;justify-content:space-between;gap:12px;align-items:center}.savebar[data-state="dirty"]{border-color:#d5ad59}.savebar[data-state="saved"]{border-color:#4b927e}.status{font-size:13px;color:var(--muted)}.person-card,.giveaway-card{padding:15px;border:1px solid #353951;border-radius:15px;background:#11131e;margin:12px 0}.pill{display:inline-block;border:1px solid #4a4d68;border-radius:999px;padding:3px 9px;color:var(--mint);font-size:12px}table{width:100%;border-collapse:collapse;display:block;overflow-x:auto}td,th{text-align:left;padding:10px;border-bottom:1px solid #303348;vertical-align:top;min-width:100px}th{color:#cbc4ee;font-size:12px;text-transform:uppercase;letter-spacing:.05em}.section-head{display:flex;justify-content:space-between;gap:12px;align-items:center;flex-wrap:wrap}@media(max-width:600px){body{margin:12px auto}.savebar{align-items:flex-start;flex-direction:column}}
</style></head><body>
<div class="hero"><div class="eyebrow">MAHZEN CONTROL ROOM</div><h1>🐢 Kaplumbik Yönetim Merkezi</h1><p class="muted">Sunucunun oyunlarını, insanlarını, etkinliklerini ve çekilişlerini tek yerden yönet. Değişiklik uyarısı ve taslak kurtarma açık.</p></div>
<div class="savebar" id="savebar" data-state="saved"><div><strong id="save-title">Her şey kayıtlı</strong><div class="status" id="save-detail">Değişiklik yaptığında burada görünecek.</div></div><span class="pill" id="save-count">0 bekleyen form</span></div>
{% with messages = get_flashed_messages() %}{% for message in messages %}<div class="flash">{{ message }}</div>{% endfor %}{% endwith %}
<a href="{{ url_for('dashboard.index') }}">← Ana panele dön</a>
<form method="post" action="{{ url_for('dashboard.advanced_save') }}"><input type="hidden" name="csrf_token" value="{{ csrf_token }}">
<section><h2>AI kişiliği ve sunucu bilgisi</h2><label>AI kişilik talimatı</label><textarea name="ai_personality" maxlength="6000">{{ values.ai_personality }}</textarea><label>Kaplumbik'in sunucu hakkında bilmesi gerekenler</label><textarea name="server_knowledge" maxlength="6000" placeholder="Mahzen'in amacı, kanallar, oyunlar, kurallar ve botun görevleri...">{{ values.server_knowledge }}</textarea><p class="muted">Buraya yazdığın bilgiler AI cevaplarına bağlam olarak eklenir. Kişi tanıtımlarını aşağıdaki ayrı bölümden yönet.</p><label>Yeni üye karşılama metni</label><textarea name="new_member_intro" maxlength="3000">{{ values.new_member_intro }}</textarea><label>Tasarımcı Discord kullanıcı ID'si</label><input name="designer_discord_id" pattern="[0-9]{15,25}" value="{{ values.designer_discord_id }}"><label>Çekiliş için gereken minimum puan</label><input name="giveaway_min_points" type="number" min="0" max="10000000" value="{{ values.giveaway_min_points }}"></section>
<section><h2>Oyun bağlantıları</h2><label>Minecraft Realms bağlantısı</label><input name="minecraft_realms_link" type="url" maxlength="500" value="{{ values.minecraft_realms_link }}"><label>Gartic Phone bağlantısı</label><input name="gartic_phone_link" type="url" maxlength="500" value="{{ values.gartic_phone_link }}"><label>Among Us oda kodu</label><input name="among_us_room_code" maxlength="100" value="{{ values.among_us_room_code }}"></section>
<section><h2>Duyuru ve hatırlatmalar</h2><label>Duyuru kanalı ID'si</label><input name="announcement_channel_id" pattern="[0-9]{15,25}" value="{{ values.announcement_channel_id }}"><label>Etkinlik duyuru kanalı ID'si (boşsa üstteki kullanılır)</label><input name="game_announcement_channel_id" pattern="[0-9]{0,25}" value="{{ values.game_announcement_channel_id }}"><label>Günlük hatırlatma metni (bot bunu aynen gönderir)</label><textarea name="daily_announcement_text" maxlength="1800">{{ values.daily_announcement_text }}</textarea><p class="muted">Metni boş bırakırsan günlük genel hatırlatma gönderilmez. Bot bu metni kendi cümleleriyle yeniden yazmaz.</p><label>Etkinlik duyuru şablonu (kendi yazın, yer tutucular otomatik doldurulur)</label><textarea name="event_announcement_template" maxlength="1800">{{ values.event_announcement_template }}</textarea><p class="muted">Kullanılabilir alanlar: {title}, {game}, {time}, {description}, {link}, {room_code}. Bunlar yalnızca etkinlik verileriyle değiştirilir; mesajın geri kalanı aynen korunur.</p><label>Günlük genel duyuru saatleri (Türkiye saati, virgülle; ör. 12:00,17:00,20:00)</label><input name="announcement_times" value="{{ values.announcement_times }}"><label>Başlangıçtan önce hatırlatma dakikaları (virgülle; ör. 15,5)</label><input name="game_reminder_minutes" value="{{ values.game_reminder_minutes }}"><label>Her duyuruda @everyone kullanılsın mı?</label><select name="announcement_everyone_ping"><option value="true" {% if values.announcement_everyone_ping == 'true' %}selected{% endif %}>Evet</option><option value="false" {% if values.announcement_everyone_ping != 'true' %}selected{% endif %}>Hayır</option></select><button type="submit">Ayarları kaydet</button></section></form>
<section><h2>👥 Kişi tanıtımları</h2><p class="muted">Sol tarafa kişinin adını, sağ tarafa onun hakkında üyelerle paylaşılmasını istediğin bilgileri yaz. Kaplumbik bu kayıtları sorulduğunda kullanır; kayıt yoksa uydurmaması gerekir. Gizli veya paylaşılmaması gereken özel bilgileri ekleme.</p><form method="post" action="{{ url_for('dashboard.person_save') }}"><input type="hidden" name="csrf_token" value="{{ csrf_token }}"><div class="grid"><div><label>Kişinin adı</label><input name="name" maxlength="100" required placeholder="Örn. Fedya"></div><div><label>Kişi hakkında bilgi</label><textarea name="info" maxlength="4000" required placeholder="İlgi alanları, sunucudaki rolü, kendisinin paylaşılmasını istediği bilgiler..."></textarea></div></div><button type="submit">Kişiyi kaydet</button></form><table><tr><th>Kişi</th><th>Bilgiler</th><th>İşlem</th></tr>{% for person in people %}<tr><td>{{ person.name }}</td><td style="white-space:pre-wrap">{{ person.info }}</td><td><form method="post" action="{{ url_for('dashboard.person_delete', person_id=person.id) }}" onsubmit="return confirm('Bu kişi tanıtımını silmek istiyor musun?')"><input type="hidden" name="csrf_token" value="{{ csrf_token }}"><button type="submit">Sil</button></form></td></tr>{% else %}<tr><td colspan="3">Henüz kişi tanıtımı eklenmedi.</td></tr>{% endfor %}</table></section><section><h2>Başarımlar</h2><p class="muted">Koşul türü ve eşikler düzenlenebilir; profillerde uygun rozetler hesaplanır.</p>
{% for item in achievements %}<form method="post" action="{{ url_for('dashboard.achievement_save', achievement_id=item.id) }}"><input type="hidden" name="csrf_token" value="{{ csrf_token }}"><strong>{{ item.key }}</strong><div class="grid"><div><label>Başlık</label><input name="title" maxlength="100" value="{{ item.title }}" required></div><div><label>Koşul türü</label><select name="condition_type">{% for kind in ['events_attended','unique_games','comeback_days','points'] %}<option value="{{ kind }}" {% if item.condition_type == kind %}selected{% endif %}>{{ kind }}</option>{% endfor %}</select></div><div><label>Eşik</label><input name="threshold" type="number" min="1" max="100000" value="{{ item.threshold }}" required></div></div><label>Açıklama</label><input name="description" maxlength="300" value="{{ item.description }}"><label><input style="width:auto" type="checkbox" name="enabled" {% if item.enabled %}checked{% endif %}> Etkin</label><button type="submit">Başarımı kaydet</button></form>{% endfor %}</section>
<section><h2>Üye arama ve puan bakiyesi</h2><form method="get" action="{{ url_for('dashboard.advanced_index') }}"><label>Discord ID veya kullanıcı adı</label><input name="member_q" value="{{ member_q }}" placeholder="ID ya da kullanıcı adı"><button type="submit">Ara</button></form><table><tr><th>Üye</th><th>Discord ID</th><th>Puan</th><th>Etkinlik puanı</th><th>Seviye</th></tr>{% for member in members %}<tr><td>{{ member.username or 'İsimsiz üye' }}</td><td>{{ member.discord_id }}</td><td>{{ member.balance }}</td><td>{{ member.total_event_points }}</td><td>{{ member.level }}</td></tr>{% else %}<tr><td colspan="5">Aramayla eşleşen üye yok.</td></tr>{% endfor %}</table></section>
<section><h2>İptal edilmiş etkinlikler</h2><p class="muted">Gelecekteki etkinlikler buradan geri alınabilir; geçmiş etkinlikler yeniden planlanmaz.</p>{% for event in cancelled_events %}<form method="post" action="{{ url_for('dashboard.restore_event', event_id=event.id) }}"><input type="hidden" name="csrf_token" value="{{ csrf_token }}"><strong>#{{ event.id }} · {{ event.title }}</strong> — {{ event.starts_at.strftime('%d.%m.%Y %H:%M') }}<button type="submit">Etkinliği geri yükle</button></form>{% else %}<p>Geri yüklenecek iptal edilmiş etkinlik yok.</p>{% endfor %}</section>
<section><h2>Son duyuru kayıtları</h2><table><tr><th>Etkinlik</th><th>Tür</th><th>Durum</th><th>Hata</th><th>Zaman</th></tr>{% for log in announcement_logs %}<tr><td>{{ log.event_id or 'Genel' }}</td><td>{{ log.kind }}</td><td>{{ 'Başarılı' if log.success else 'Hata' }}</td><td>{{ log.error or '' }}</td><td>{{ log.sent_at.strftime('%d.%m %H:%M:%S') }}{% if log.event_id %}<form method="post" action="{{ url_for('dashboard.resend_announcement', log_id=log.id) }}"><input type="hidden" name="csrf_token" value="{{ csrf_token }}"><button type="submit">Yeniden gönder</button></form>{% endif %}</td></tr>{% else %}<tr><td colspan="5">Henüz duyuru kaydı yok.</td></tr>{% endfor %}</table></section>
<section><h2>Yönetici işlem kayıtları</h2><table><tr><th>Yönetici</th><th>İşlem</th><th>Hedef</th><th>Başarılı</th><th>Zaman</th></tr>{% for row in audit_logs %}<tr><td>{{ row.actor_discord_id }}</td><td>{{ row.action }}</td><td>{{ row.target_type }} · {{ row.target_id }}</td><td>{{ 'Evet' if row.success else 'Hayır' }}</td><td>{{ row.created_at.strftime('%d.%m %H:%M:%S') if row.created_at else '' }}</td></tr>{% else %}<tr><td colspan="5">Henüz işlem kaydı yok.</td></tr>{% endfor %}</table></section>
<section><h2>Son sağlık kayıtları</h2><table><tr><th>Bileşen</th><th>Durum</th><th>Detay</th><th>Zaman</th></tr>{% for row in health %}<tr><td>{{ row.component }}</td><td>{{ row.status }}</td><td>{{ row.details or '' }}</td><td>{{ row.checked_at.strftime('%d.%m %H:%M:%S') }}</td></tr>{% else %}<tr><td colspan="4">Henüz sağlık kaydı yok.</td></tr>{% endfor %}</table></section>
</body></html>
"""

SETTING_KEYS = (
    "ai_personality", "server_knowledge", "daily_announcement_text", "event_announcement_template", "new_member_intro", "designer_discord_id",
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
    values["daily_announcement_text"] = get_setting("daily_announcement_text", "")
    values["event_announcement_template"] = get_setting("event_announcement_template", "")
    values["server_knowledge"] = get_setting("server_knowledge", "")
    people = db.session.query(PersonProfile).order_by(PersonProfile.name.asc()).limit(200).all()
    achievements = db.session.query(AchievementDefinition).order_by(AchievementDefinition.id).all()
    health = health_snapshot(30)
    audit_logs = db.session.query(AuditLog).order_by(AuditLog.id.desc()).limit(50).all()
    announcement_logs = db.session.query(AnnouncementLog).order_by(AnnouncementLog.sent_at.desc()).limit(30).all()
    cancelled_events = db.session.query(Event).filter_by(status="cancelled").order_by(Event.starts_at.desc()).limit(30).all()
    member_q = request.args.get("member_q", "").strip()[:100]
    member_query = db.session.query(UserProfile)
    if member_q:
        from sqlalchemy import or_
        member_query = member_query.filter(or_(UserProfile.discord_id == member_q, UserProfile.username.ilike(f"%{member_q}%")))
    members = member_query.order_by(UserProfile.balance.desc()).limit(100).all()
    return render_template_string(SETTINGS_PAGE, values=values, people=people, achievements=achievements, health=health, audit_logs=audit_logs, announcement_logs=announcement_logs, cancelled_events=cancelled_events, members=members, member_q=member_q, csrf_token=session.get("csrf_token", ""))


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
        if len(values["daily_announcement_text"]) > 1800 or len(values["event_announcement_template"]) > 1800:
            raise ValueError("Duyuru metinleri en fazla 1800 karakter olabilir.")
        times = [part.strip() for part in request.form.get("announcement_times", "12:00,17:00,20:00").split(",") if part.strip()]
        for item in times:
            datetime.strptime(item, "%H:%M")
        values["announcement_times"] = ",".join(dict.fromkeys(times[:12]))
        reminders = [int(part.strip()) for part in values["game_reminder_minutes"].split(",") if part.strip()]
        if any(n < 1 or n > 1440 for n in reminders):
            raise ValueError("Hatırlatma dakikaları 1–1440 aralığında olmalı.")
        values["game_reminder_minutes"] = ",".join(map(str, sorted(set(reminders), reverse=True)))
        for key, value in values.items():
            row = db.session.get(BotSetting, key)
            if row is None:
                row = BotSetting(key=key, value=value)
                db.session.add(row)
            else:
                row.value = value
            row.updated_by = actor
        db.session.add(AuditLog(actor_discord_id=actor, action="settings.update", target_type="bot_settings", target_id="all", details={"keys": list(values)}, success=True))
        db.session.commit()
        flash("Gelişmiş ayarlar kaydedildi.")
    except Exception as exc:
        db.session.rollback()
        logger.exception("Could not save advanced settings")
        flash(f"Ayarlar kaydedilemedi: {str(exc)[:180]}")
    return redirect(url_for("dashboard.advanced_index"))


@dashboard_bp.post("/advanced/people")
@owner_required
def person_save():
    _require_csrf()
    name = request.form.get("name", "").strip()
    info = request.form.get("info", "").strip()
    if not name or not info:
        flash("Kişinin adı ve hakkında bilgi alanları boş bırakılamaz.")
        return redirect(url_for("dashboard.advanced_index"))
    if len(name) > 100 or len(info) > 4000:
        flash("Kişi adı en fazla 100, bilgi metni en fazla 4000 karakter olabilir.")
        return redirect(url_for("dashboard.advanced_index"))
    try:
        person = PersonProfile(name=name, info=info)
        db.session.add(person)
        db.session.flush()
        db.session.add(AuditLog(
            actor_discord_id=str(session["discord_id"]),
            action="person.create", target_type="person_profile", target_id=str(person.id),
            details={"name": name}, success=True,
        ))
        db.session.commit()
        flash(f"{name} için kişi tanıtımı kaydedildi.")
    except Exception as exc:
        db.session.rollback()
        logger.exception("Could not save person profile")
        flash("Kişi kaydedilemedi. Veritabanı hatasını kontrol et.")
    return redirect(url_for("dashboard.advanced_index"))


@dashboard_bp.post("/advanced/people/<int:person_id>/delete")
@owner_required
def person_delete(person_id):
    _require_csrf()
    person = db.session.get(PersonProfile, person_id)
    if person is None:
        flash("Bu kişi tanıtımı zaten bulunmuyor.")
        return redirect(url_for("dashboard.advanced_index"))
    try:
        name = person.name
        db.session.add(AuditLog(
            actor_discord_id=str(session["discord_id"]),
            action="person.delete", target_type="person_profile", target_id=str(person.id),
            details={"name": name}, success=True,
        ))
        db.session.delete(person)
        db.session.commit()
        flash(f"{name} için kişi tanıtımı silindi.")
    except Exception:
        db.session.rollback()
        logger.exception("Could not delete person profile")
        flash("Kişi tanıtımı silinemedi.")
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


@dashboard_bp.post("/advanced/announcements/<int:log_id>/resend")
@owner_required
def resend_announcement(log_id):
    _require_csrf()
    log = db.session.get(AnnouncementLog, log_id)
    try:
        if log is None or log.event_id is None:
            raise ValueError("Yeniden gönderilecek etkinlik duyurusu bulunamadı.")
        event = db.session.get(Event, log.event_id)
        if event is None:
            raise ValueError("Etkinlik artık bulunamıyor.")
        if event.status != "scheduled":
            raise ValueError("Yalnızca planlanmış etkinliklerin duyuruları yeniden gönderilebilir.")
        set_setting("resend_event_id", str(event.id), str(session["discord_id"]))
        db.session.add(AuditLog(actor_discord_id=str(session["discord_id"]), action="announcement.resend_requested", target_type="event", target_id=str(event.id), details={"log_id": log_id}, success=True))
        db.session.commit()
        flash(f"Etkinlik #{event.id} için yeniden gönderim isteği kuyruğa alındı.")
    except Exception as exc:
        db.session.rollback()
        logger.exception("Could not queue announcement resend")
        flash(f"Yeniden gönderim kuyruğa alınamadı: {str(exc)[:180]}")
    return redirect(url_for("dashboard.advanced_index"))

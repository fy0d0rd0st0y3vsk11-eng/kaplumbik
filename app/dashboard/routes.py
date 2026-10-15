import logging
import secrets
from datetime import datetime, timezone
from functools import wraps
from zoneinfo import ZoneInfo

import discord
from authlib.integrations.flask_client import OAuth
from werkzeug.exceptions import HTTPException

from flask import (
    abort,
    flash,
    redirect,
    render_template_string,
    request,
    session,
    url_for,
)

from app.core.config import settings
from app.database import db
from app.database.event_models import Event, EventParticipation
from app.database.models import AuditLog, EconomyTransaction, UserProfile
from app.economy.service import (
    DuplicateTransactionError,
    UserNotFoundError,
    adjust_balance,
)
from app.events.service import (
    EventServiceError,
    cancel_event,
    create_event,
    record_attendance,
)
from . import dashboard_bp

logger = logging.getLogger("kaplumbik.dashboard")
oauth = OAuth()
discord_oauth = oauth.register(
    name="discord",
    client_id=settings.discord_client_id,
    client_secret=settings.discord_client_secret,
    authorize_url="https://discord.com/oauth2/authorize",
    access_token_url="https://discord.com/api/oauth2/token",
    api_base_url="https://discord.com/api/",
    client_kwargs={"scope": "identify"},
)

PAGE = """
<!doctype html>
<html lang="tr">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{ title }} · Kaplumbik</title>
<style>
:root{color-scheme:dark;--bg:#101117;--panel:#191b25;--line:#303342;--text:#f4f4f8;--muted:#a8a9bb;--accent:#a78bfa;--good:#86efac;--bad:#fca5a5}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:15px/1.5 system-ui,-apple-system,sans-serif}
header{padding:22px max(18px,calc((100% - 1180px)/2));border-bottom:1px solid var(--line);display:flex;align-items:center;justify-content:space-between;gap:16px}
main{max-width:1180px;margin:26px auto;padding:0 18px 48px}h1{font-size:26px;margin:0}h2{font-size:18px;margin:0 0 14px}p,.muted{color:var(--muted)}a{color:#c4b5fd}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(270px,1fr));gap:16px}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:16px;padding:18px;margin-bottom:16px}.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin-bottom:18px}.stat{background:var(--panel);border:1px solid var(--line);border-radius:13px;padding:15px}.stat strong{font-size:25px;display:block}
label{display:block;color:var(--muted);font-size:13px;margin:10px 0 5px}input,textarea,select{width:100%;padding:10px 11px;border-radius:9px;border:1px solid var(--line);background:#101117;color:var(--text);font:inherit}
textarea{min-height:75px;resize:vertical}button,.button{border:0;border-radius:9px;background:var(--accent);color:#171322;font-weight:700;padding:10px 13px;cursor:pointer;text-decoration:none;display:inline-block;margin-top:10px}button.secondary{background:#353747;color:var(--text)}button.danger{background:#7f1d1d;color:#fff}
form{margin:0 0 12px}.row{display:grid;grid-template-columns:1fr 1fr;gap:10px}.event{padding:13px 0;border-top:1px solid var(--line)}.event:first-of-type{border-top:0}.tag{font-size:12px;border-radius:99px;background:#303044;padding:3px 8px;color:#ddd}.flash{padding:11px 13px;border-radius:10px;background:#29263c;margin-bottom:12px}.empty{color:var(--muted);padding:12px 0}
table{width:100%;border-collapse:collapse}th,td{text-align:left;padding:9px;border-bottom:1px solid var(--line);font-size:13px;overflow-wrap:anywhere}th{color:var(--muted)}.table-wrap{overflow-x:auto}
@media(max-width:600px){.row{grid-template-columns:1fr}header{align-items:flex-start}h1{font-size:22px}}
</style></head><body>
<header><div><h1>🐢 Kaplumbik</h1><div class="muted">Mahzen yönetim paneli</div></div>
{% if logged_in %}<div><span class="muted">{{ username }}</span> <a class="button" href="{{ url_for('dashboard.logout') }}">Çıkış</a></div>{% endif %}</header>
<main>
{% for message in get_flashed_messages() %}<div class="flash">{{ message }}</div>{% endfor %}
{% if not logged_in %}
<section class="panel"><h2>Güvenli yönetici girişi</h2><p>Panel yalnızca yapılandırılmış sunucu sahibinin Discord hesabına açıktır.</p><a class="button" href="{{ url_for('dashboard.login') }}">Discord ile giriş yap</a></section>
{% else %}
<div class="stats">
<div class="stat"><span class="muted">Üye profilleri</span><strong>{{ stats.members }}</strong></div>
<div class="stat"><span class="muted">Planlanmış etkinlik</span><strong>{{ stats.events }}</strong></div>
<div class="stat"><span class="muted">Toplam puan hareketi</span><strong>{{ stats.transactions }}</strong></div>
<div class="stat"><span class="muted">Denetim kaydı</span><strong>{{ stats.audit }}</strong></div>
</div>
<div class="grid">
<section class="panel"><h2>＋ Etkinlik oluştur</h2>
<form method="post" action="{{ url_for('dashboard.create_event_route') }}">
<input type="hidden" name="csrf_token" value="{{ csrf_token }}">
<label>Etkinlik adı</label><input name="title" maxlength="150" required>
<div class="row"><div><label>Oyun</label><input name="game" maxlength="80" required></div><div><label>Başlangıç (Türkiye saati)</label><input type="datetime-local" name="starts_at" required></div></div>
<label>Açıklama</label><textarea name="description" maxlength="2000"></textarea>
<label>Oyun bağlantısı</label><input name="game_link" type="url" maxlength="500" placeholder="https://...">
<label>Oda kodu (panelde tutulur, herkese açık duyuruda gösterilmez)</label><input name="room_code" maxlength="100">
<button type="submit">Etkinliği kaydet</button></form></section>
<section class="panel"><h2>＋ Üye puanını düzenle</h2>
<form method="post" action="{{ url_for('dashboard.adjust_points_route') }}">
<input type="hidden" name="csrf_token" value="{{ csrf_token }}">
<label>Üyenin Discord kullanıcı ID'si</label><input name="discord_id" inputmode="numeric" pattern="[0-9]{15,25}" required>
<label>Kullanıcı adı (bilinmiyorsa boş bırak)</label><input name="username" maxlength="100">
<div class="row"><div><label>Puan (+ ekle / − çıkar)</label><input name="amount" type="number" min="-1000000" max="1000000" required></div><div><label>İşlem açıklaması</label><input name="description" maxlength="300" required></div></div>
<button type="submit">Puan hareketini kaydet</button></form></section>
</div>
<section class="panel"><h2>Etkinlikler</h2>
{% if events %}{% for event in events %}
<div class="event"><strong>#{{ event.id }} · {{ event.title }}</strong> <span class="tag">{{ event.status }}</span>
<div class="muted">{{ event.game }} · {{ event.starts_at.strftime('%d.%m.%Y %H:%M') }} UTC</div>
{% if event.description %}<p>{{ event.description }}</p>{% endif %}
{% if event.game_link %}<p><a href="{{ event.game_link }}" rel="noopener noreferrer" target="_blank">Oyun bağlantısı</a></p>{% endif %}
<div class="muted">Katılım kayıtları: {{ event.participations|length }}</div>
{% if event.status == 'scheduled' %}
<details><summary>Katılımı yönet / ödül ver</summary>
{% for member in event.participations %}
<form method="post" action="{{ url_for('dashboard.attendance_route', event_id=event.id) }}" class="event">
<input type="hidden" name="csrf_token" value="{{ csrf_token }}"><input type="hidden" name="discord_id" value="{{ member.discord_id }}">
<strong>Üye ID: {{ member.discord_id }}</strong> <span class="tag">{{ member.status }}</span>
<div class="row"><div><label>Yoklama</label><select name="status"><option value="attended" {% if member.status == 'attended' %}selected{% endif %}>Katıldı</option><option value="absent" {% if member.status == 'absent' %}selected{% endif %}>Katılmadı</option></select></div><div><label>Verilecek puan (katıldıysa)</label><input name="reward_points" type="number" min="0" max="100000" value="0"></div></div>
<button type="submit">Yoklamayı kaydet</button>{% if member.reward_approved %}<span class="tag">Ödül onaylandı</span>{% endif %}</form>
{% endfor %}
<form method="post" action="{{ url_for('dashboard.cancel_event_route', event_id=event.id) }}"><input type="hidden" name="csrf_token" value="{{ csrf_token }}"><button class="danger" type="submit">Etkinliği iptal et</button></form>
</details>{% endif %}
</div>{% endfor %}{% else %}<div class="empty">Henüz etkinlik yok.</div>{% endif %}
</section>
<section class="panel"><h2>Üyeler ve bakiyeler</h2>
<form method="get" action="{{ url_for('dashboard.index') }}">
<label>Discord ID veya kullanıcı adına göre ara</label><input name="q" value="{{ member_query }}" maxlength="100" placeholder="Üye ara…">
<button type="submit">Ara</button> {% if member_query %}<a href="{{ url_for('dashboard.index') }}">Temizle</a>{% endif %}
</form>
<div class="table-wrap"><table><thead><tr><th>Kullanıcı</th><th>Discord ID</th><th>Bakiye</th><th>Etkinlik puanı</th><th>Seviye</th><th>Son etkinlik</th></tr></thead><tbody>
{% for member in members %}<tr><td>{{ member.username or 'İsimsiz üye' }}</td><td>{{ member.discord_id }}</td><td>{{ member.balance }}</td><td>{{ member.total_event_points }}</td><td>{{ member.level }}</td><td>{{ member.last_event_at.strftime('%d.%m.%Y') if member.last_event_at else '—' }}</td></tr>{% else %}<tr><td colspan="6">Üye bulunamadı.</td></tr>{% endfor %}
</tbody></table></div></section>
<div class="grid">
<section class="panel"><h2>Son puan hareketleri</h2><div class="table-wrap"><table><thead><tr><th>Üye ID</th><th>Miktar</th><th>Açıklama</th><th>Tarih</th></tr></thead><tbody>
{% for tx in transactions %}<tr><td>{{ tx.user.discord_id if tx.user else tx.user_id }}</td><td>{{ '+' if tx.amount > 0 else '' }}{{ tx.amount }}</td><td>{{ tx.description }}</td><td>{{ tx.created_at.strftime('%d.%m %H:%M') }}</td></tr>{% else %}<tr><td colspan="4">Kayıt yok.</td></tr>{% endfor %}
</tbody></table></div></section>
<section class="panel"><h2>Denetim geçmişi</h2><div class="table-wrap"><table><thead><tr><th>İşlem</th><th>Yetkili</th><th>Hedef</th><th>Tarih</th></tr></thead><tbody>
{% for item in audit_logs %}<tr><td>{{ item.action }}</td><td>{{ item.actor_discord_id or '—' }}</td><td>{{ item.target_id or '—' }}</td><td>{{ item.created_at.strftime('%d.%m %H:%M') }}</td></tr>{% else %}<tr><td colspan="4">Kayıt yok.</td></tr>{% endfor %}
</tbody></table></div></section>
</div>
{% endif %}
</main></body></html>
"""


def _csrf_token():
    token = session.get("csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["csrf_token"] = token
    return token


def _require_csrf():
    expected = session.get("csrf_token", "")
    supplied = request.form.get("csrf_token", "")
    if not expected or not supplied or not secrets.compare_digest(expected, supplied):
        abort(400, description="Form güvenlik doğrulaması başarısız.")


def owner_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        owner_id = str(settings.owner_discord_id or "").strip()
        current_id = str(session.get("discord_id", "")).strip()
        if not owner_id:
            abort(503, description="OWNER_DISCORD_ID ortam değişkeni ayarlanmamış.")
        if not current_id:
            flash("Önce Discord hesabınla giriş yapmalısın.")
            return redirect(url_for("dashboard.index"))
        if not secrets.compare_digest(current_id, owner_id):
            session.clear()
            abort(403, description="Bu panel yalnızca sunucu sahibi için açık.")
        return view(*args, **kwargs)
    return wrapped


@dashboard_bp.get("/")
def index():
    logged_in = bool(session.get("discord_id"))
    if not logged_in:
        return render_template_string(
            PAGE, title="Giriş", logged_in=False, username="", csrf_token="",
            stats={}, events=[], transactions=[], audit_logs=[]
        )

    owner_id = str(settings.owner_discord_id or "").strip()
    if not owner_id or not secrets.compare_digest(str(session["discord_id"]), owner_id):
        session.clear()
        abort(403, description="Bu panel yalnızca sunucu sahibi için açık.")

    from sqlalchemy import select, func, or_

    member_query = request.args.get("q", "").strip()[:100]
    member_stmt = select(UserProfile).order_by(UserProfile.updated_at.desc())
    if member_query:
        member_stmt = member_stmt.where(or_(
            UserProfile.discord_id.contains(member_query),
            UserProfile.username.ilike(f"%{member_query}%"),
        ))
    members = list(db.session.execute(member_stmt.limit(100)).scalars())
    events = list(db.session.execute(
        select(Event).order_by(Event.starts_at.desc()).limit(50)
    ).scalars())
    transactions = list(db.session.execute(
        select(EconomyTransaction).order_by(EconomyTransaction.created_at.desc()).limit(12)
    ).scalars())
    audit_logs = list(db.session.execute(
        select(AuditLog).order_by(AuditLog.created_at.desc()).limit(12)
    ).scalars())
    stats = {
        "members": db.session.scalar(select(func.count(UserProfile.id))) or 0,
        "events": db.session.scalar(select(func.count(Event.id)).where(Event.status == "scheduled")) or 0,
        "transactions": db.session.scalar(select(func.count(EconomyTransaction.id))) or 0,
        "audit": db.session.scalar(select(func.count(AuditLog.id))) or 0,
    }
    return render_template_string(
        PAGE, title="Panel", logged_in=True,
        username=session.get("username", "Yönetici"),
        csrf_token=_csrf_token(), stats=stats, events=events,
        transactions=transactions, audit_logs=audit_logs,
        members=members, member_query=member_query
    )


@dashboard_bp.get("/login")
def login():
    if not settings.discord_client_id or not settings.discord_client_secret:
        abort(503, description="Discord OAuth için DISCORD_CLIENT_ID ve DISCORD_CLIENT_SECRET ayarlanmalı.")
    redirect_uri = settings.discord_redirect_uri
    return discord_oauth.authorize_redirect(redirect_uri)


@dashboard_bp.get("/callback")
def callback():
    if not settings.discord_client_id or not settings.discord_client_secret:
        abort(503, description="Discord OAuth ayarları eksik.")
    try:
        token = discord_oauth.authorize_access_token()
        response = discord_oauth.get("users/@me")
        response.raise_for_status()
        user = response.json()
        discord_id = str(user.get("id", ""))
        owner_id = str(settings.owner_discord_id or "").strip()
        if not discord_id or not owner_id or not secrets.compare_digest(discord_id, owner_id):
            session.clear()
            abort(403, description="Bu Discord hesabının yönetim paneli erişimi yok.")
        session.clear()
        session["discord_id"] = discord_id
        session["username"] = str(user.get("global_name") or user.get("username") or "Yönetici")[:100]
        session["csrf_token"] = secrets.token_urlsafe(32)
        return redirect(url_for("dashboard.index"))
    except HTTPException:
        raise
    except Exception:
        logger.exception("Discord OAuth callback failed.")
        abort(502, description="Discord girişi tamamlanamadı. OAuth URL ve anahtarları kontrol et.")


@dashboard_bp.get("/logout")
def logout():
    session.clear()
    flash("Oturum kapatıldı.")
    return redirect(url_for("dashboard.index"))


@dashboard_bp.post("/events")
@owner_required
def create_event_route():
    _require_csrf()
    try:
        title = request.form.get("title", "").strip()
        game = request.form.get("game", "").strip()
        local_start = datetime.fromisoformat(request.form.get("starts_at", ""))
        if local_start.tzinfo is None:
            local_start = local_start.replace(tzinfo=ZoneInfo("Europe/Istanbul"))
        event = create_event(
            title=title, game=game, starts_at=local_start,
            created_by=str(session["discord_id"]),
            description=request.form.get("description", ""),
            game_link=request.form.get("game_link", ""),
            room_code=request.form.get("room_code", ""),
        )
        db.session.add(AuditLog(
            actor_discord_id=str(session["discord_id"]), action="event.create",
            target_type="event", target_id=str(event.id),
            details={"title": event.title, "game": event.game}, success=True,
        ))
        db.session.commit()
        flash(f"Etkinlik #{event.id} oluşturuldu.")
    except Exception as exc:
        db.session.rollback()
        logger.exception("Dashboard event creation failed.")
        flash(f"Etkinlik kaydedilemedi: {str(exc)[:180]}")
    return redirect(url_for("dashboard.index"))


@dashboard_bp.post("/members/points")
@owner_required
def adjust_points_route():
    _require_csrf()
    try:
        discord_id = request.form.get("discord_id", "").strip()
        username = request.form.get("username", "").strip()[:100]
        amount = int(request.form.get("amount", "0"))
        description = request.form.get("description", "").strip()[:300]
        if not discord_id.isdigit() or not 15 <= len(discord_id) <= 25:
            raise ValueError("Geçerli bir Discord kullanıcı ID'si gir.")
        if amount == 0 or abs(amount) > 1_000_000:
            raise ValueError("Puan miktarı sıfırdan farklı ve 1.000.000 sınırında olmalı.")
        if not description:
            raise ValueError("İşlem açıklaması gerekli.")
        profile = db.session.execute(
            db.select(UserProfile).where(UserProfile.discord_id == discord_id)
        ).scalar_one_or_none()
        if profile is None:
            profile = UserProfile(discord_id=discord_id, username=username or None)
            db.session.add(profile)
            db.session.commit()
        elif username:
            profile.username = username
            db.session.commit()
        tx = adjust_balance(
            discord_id=discord_id, amount=amount,
            transaction_type="admin_adjustment", description=description,
            actor_discord_id=str(session["discord_id"]),
        )
        db.session.add(AuditLog(
            actor_discord_id=str(session["discord_id"]), action="economy.adjust",
            target_type="member", target_id=discord_id,
            details={"amount": amount, "transaction_id": tx.id, "description": description},
            success=True,
        ))
        db.session.commit()
        flash(f"Puan hareketi kaydedildi. Yeni bakiye: {tx.balance_after}.")
    except Exception as exc:
        db.session.rollback()
        logger.exception("Dashboard point adjustment failed.")
        flash(f"Puan değişikliği yapılamadı: {str(exc)[:180]}")
    return redirect(url_for("dashboard.index"))


@dashboard_bp.post("/events/<int:event_id>/cancel")
@owner_required
def cancel_event_route(event_id):
    _require_csrf()
    try:
        event = cancel_event(event_id)
        db.session.add(AuditLog(
            actor_discord_id=str(session["discord_id"]), action="event.cancel",
            target_type="event", target_id=str(event.id), details={}, success=True,
        ))
        db.session.commit()
        flash(f"Etkinlik #{event.id} iptal edildi; geçmiş kaydı korundu.")
    except Exception as exc:
        db.session.rollback()
        logger.exception("Dashboard event cancellation failed.")
        flash(f"Etkinlik iptal edilemedi: {str(exc)[:180]}")
    return redirect(url_for("dashboard.index"))


@dashboard_bp.post("/events/<int:event_id>/attendance")
@owner_required
def attendance_route(event_id):
    _require_csrf()
    discord_id = request.form.get("discord_id", "").strip()
    status = request.form.get("status", "").strip()
    try:
        points = int(request.form.get("reward_points", "0"))
        if points < 0 or points > 100_000:
            raise ValueError("Ödül 0 ile 100.000 arasında olmalı.")
        event = db.session.get(Event, event_id)
        if event is None:
            raise ValueError("Etkinlik bulunamadı.")
        existing = db.session.execute(db.select(EventParticipation).where(
            EventParticipation.event_id == event_id,
            EventParticipation.discord_id == discord_id,
        )).scalar_one_or_none()
        reward_was_approved = bool(existing and existing.reward_approved)
        if reward_was_approved and points:
            raise ValueError("Bu ödül daha önce onaylanmış; ikinci kez verilemez.")
        participation = record_attendance(
            event_id=event_id, discord_id=discord_id, status=status,
            manager_discord_id=str(session["discord_id"]),
        )
        if status == "attended" and points > 0 and not participation.reward_approved:
            profile = db.session.execute(db.select(UserProfile).where(
                UserProfile.discord_id == discord_id
            )).scalar_one_or_none()
            if profile is None:
                profile = UserProfile(discord_id=discord_id)
                db.session.add(profile)
                db.session.commit()
            key = f"event-reward:{event_id}:{discord_id}"
            try:
                tx = adjust_balance(
                    discord_id=discord_id, amount=points,
                    transaction_type="event_reward",
                    description=f"Etkinlik ödülü: {event.title}",
                    actor_discord_id=str(session["discord_id"]),
                    idempotency_key=key,
                )
            except DuplicateTransactionError:
                tx = db.session.execute(db.select(EconomyTransaction).where(
                    EconomyTransaction.idempotency_key == key
                )).scalar_one_or_none()
                if tx is None:
                    raise
            participation.reward_approved = True
            participation.reward_transaction_id = tx.id
            tx.reference_type = "event"
            tx.reference_id = str(event_id)
            if not reward_was_approved:\n                profile.total_event_points += points
        db.session.add(AuditLog(
            actor_discord_id=str(session["discord_id"]), action="event.attendance",
            target_type="event_participation", target_id=f"{event_id}:{discord_id}",
            details={"status": status, "reward_points": points if status == "attended" else 0},
            success=True,
        ))
        db.session.commit()
        flash("Yoklama ve varsa puan ödülü kaydedildi.")
    except Exception as exc:
        db.session.rollback()
        logger.exception("Dashboard attendance update failed.")
        flash(f"Yoklama kaydedilemedi: {str(exc)[:180]}")
    return redirect(url_for("dashboard.index"))

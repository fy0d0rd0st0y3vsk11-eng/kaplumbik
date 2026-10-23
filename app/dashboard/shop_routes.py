import logging
import re

from flask import flash, redirect, render_template_string, request, session, url_for
from sqlalchemy import select

from app.dashboard import dashboard_bp
from app.dashboard.routes import owner_required, _require_csrf
from app.database import db
from app.database.community_models import RewardShopItem, MemberCollectionItem
from app.database.models import AuditLog

log = logging.getLogger("kaplumbik.dashboard.shop")

SHOP_PAGE = """
<!doctype html>
<html lang="tr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Mağaza yönetimi · Kaplumbik</title>
<style>
:root{color-scheme:light;--bg:#f5f3eb;--panel:#fffdf7;--line:#d9dfd0;--text:#30382f;--muted:#737d70;--accent:#a38a68;--danger:#9b3939}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:15px/1.55 system-ui,sans-serif}
header,main{max-width:1100px;margin:auto;padding:20px}header{display:flex;justify-content:space-between;align-items:center;gap:12px;border-bottom:1px solid var(--line)}
h1{font-size:25px;margin:0}h2{font-size:19px;margin:0 0 12px}h3{font-size:16px;margin:0}
.panel,.item{background:var(--panel);border:1px solid var(--line);border-radius:15px;padding:18px;margin:16px 0}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:12px}
label{display:block;font-size:13px;color:var(--muted);margin:9px 0 4px}
input,textarea,select{width:100%;padding:10px;border:1px solid var(--line);border-radius:9px;background:var(--panel);color:var(--text);font:inherit}
textarea{min-height:70px;resize:vertical}
button,.button{display:inline-block;border:0;border-radius:9px;padding:10px 13px;margin-top:10px;background:var(--accent);color:#211c16;font-weight:700;text-decoration:none;cursor:pointer}
button.danger{background:var(--danger);color:white}button.secondary{background:#d9dfd0}
.muted{color:var(--muted)}.pill{font-size:12px;border:1px solid var(--line);padding:3px 8px;border-radius:99px}
.item-head{display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap}
.flash{padding:10px 12px;background:#e9e4d7;border-radius:9px;margin:12px 0}
hr{border:0;border-top:1px solid var(--line);margin:16px 0}
@media(max-width:600px){header{align-items:flex-start;flex-direction:column}}
</style></head><body>
<header><div><h1>🐢 Mahzen mağazası</h1><div class="muted">Ürünleri buradan ekle, düzenle ve yayına al.</div></div><a class="button" href="{{ url_for('dashboard.index') }}">← Ana panele dön</a></header>
<main>
{% for message in get_flashed_messages() %}<div class="flash">{{ message }}</div>{% endfor %}
<section class="panel"><h2>＋ Yeni ürün ekle</h2>
<p class="muted">Ürün kaydedildiğinde /dukkan listesinde görünür. Anahtar, üyelerin /dukkanal komutunda kullanacağı benzersiz kısa addır. Rol ürünlerinde botun rolü verebileceği bir rol ID'si gir.</p>
<form method="post" action="{{ url_for('dashboard.shop_create') }}">
<input type="hidden" name="csrf_token" value="{{ csrf_token }}">
<div class="grid">
<div><label>Ürün anahtarı (benzersiz)</label><input name="key" maxlength="80" pattern="[A-Za-z0-9_-]+" required placeholder="custom_color"></div>
<div><label>Mağazada görünen ad</label><input name="title" maxlength="120" required placeholder="Özel renk rolü"></div>
<div><label>Fiyat (coin)</label><input name="price" type="number" min="0" max="1000000" required value="500"></div>
<div><label>Ürün türü</label><select name="item_type"><option value="cosmetic">Kozmetik / unvan</option><option value="role">Discord rolü</option><option value="badge">Rozet</option><option value="collection">Koleksiyon</option></select></div>
<div><label>Discord rol ID'si (yalnızca rol ürünü)</label><input name="discord_role_id" inputmode="numeric" pattern="[0-9]{15,25}" placeholder="İsteğe bağlı, rol türünde gerekli"></div>
<div><label>Süre (gün, boşsa kalıcı)</label><input name="duration_days" type="number" min="1" max="3650" placeholder="Örn. 7"></div>
</div>
<label>Açıklama</label><textarea name="description" maxlength="300" placeholder="Ürün açıklaması ve ne kazandırdığı" ></textarea>
<button type="submit">Ürünü kaydet</button></form></section>
<section class="panel"><h2>Mağaza ürünleri · {{ items|length }}</h2>
{% for item in items %}
<div class="item"><div class="item-head"><h3>{{ item.title }} <span class="pill">{{ item.item_type }}</span></h3><span class="pill">{{ 'Yayında' if item.enabled else 'Gizli' }}</span></div>
<p>{{ item.description or 'Açıklama yok.' }}</p><p><strong>{{ item.price }} coin</strong> · Anahtar: <code>{{ item.key }}</code>{% if item.duration_days %} · {{ item.duration_days }} gün{% else %} · Kalıcı{% endif %}{% if item.discord_role_id %} · Rol ID: {{ item.discord_role_id }}{% endif %}</p>
<form method="post" action="{{ url_for('dashboard.shop_update', item_id=item.id) }}">
<input type="hidden" name="csrf_token" value="{{ csrf_token }}"><input type="hidden" name="key" value="{{ item.key }}">
<div class="grid">
<div><label>Görünen ad</label><input name="title" maxlength="120" value="{{ item.title }}" required></div>
<div><label>Fiyat</label><input name="price" type="number" min="0" max="1000000" value="{{ item.price }}" required></div>
<div><label>Tür</label><select name="item_type">{% for kind,label in kinds %}<option value="{{ kind }}" {% if item.item_type == kind %}selected{% endif %}>{{ label }}</option>{% endfor %}</select></div>
<div><label>Discord rol ID'si</label><input name="discord_role_id" inputmode="numeric" pattern="[0-9]{15,25}" value="{{ item.discord_role_id or '' }}" placeholder="Rol türünde gerekli"></div>
<div><label>Süre (gün, boşsa kalıcı)</label><input name="duration_days" type="number" min="1" max="3650" value="{{ item.duration_days or '' }}"></div>
</div>
<label>Açıklama</label><textarea name="description" maxlength="300">{{ item.description or '' }}</textarea>
<label><input style="width:auto" type="checkbox" name="enabled" value="yes" {% if item.enabled %}checked{% endif %}> Mağazada görünür ve satın alınabilir</label>
<button type="submit">Değişiklikleri kaydet</button>
</form>
<form method="post" action="{{ url_for('dashboard.shop_delete', item_id=item.id) }}" onsubmit="return confirm('Bu ürünü kalıcı silmek yerine mağazada gizlemek istiyorsun. Devam edilsin mi?')">
<input type="hidden" name="csrf_token" value="{{ csrf_token }}"><button class="danger" type="submit">Ürünü gizle</button>
</form>
</div>
{% else %}<p class="muted">Henüz ürün yok. Yukarıdaki formdan ilk ürünü ekleyebilirsin.</p>{% endfor %}
</section>
</main></body></html>
"""

KINDS = {
    "cosmetic": "Kozmetik / unvan",
    "role": "Discord rolü",
    "badge": "Rozet",
    "collection": "Koleksiyon",
}


def _read_product_form():
    key = request.form.get("key", "").strip()[:80]
    title = request.form.get("title", "").strip()[:120]
    description = request.form.get("description", "").strip()[:300]
    item_type = request.form.get("item_type", "cosmetic").strip()
    role_id = request.form.get("discord_role_id", "").strip()
    duration_raw = request.form.get("duration_days", "").strip()
    try:
        price = int(request.form.get("price", ""))
        duration = int(duration_raw) if duration_raw else None
    except (TypeError, ValueError):
        raise ValueError("Fiyat ve süre sayısal olmalı.")
    if not key or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", key):
        raise ValueError("Ürün anahtarı yalnızca İngilizce harf, sayı, tire ve alt çizgi içermeli.")
    if not title:
        raise ValueError("Ürün adı boş bırakılamaz.")
    if item_type not in KINDS:
        raise ValueError("Ürün türü geçersiz.")
    if not 0 <= price <= 1_000_000:
        raise ValueError("Fiyat 0–1.000.000 coin arasında olmalı.")
    if duration is not None and not 1 <= duration <= 3650:
        raise ValueError("Süre 1–3650 gün arasında olmalı.")
    if role_id and not re.fullmatch(r"[0-9]{15,25}", role_id):
        raise ValueError("Discord rol ID'si geçersiz.")
    if item_type == "role" and not role_id:
        raise ValueError("Rol ürünü için Discord rol ID'si gerekli.")
    return key, title, description, item_type, price, role_id or None, duration


@dashboard_bp.get("/shop")
@owner_required
def shop_index():
    items = db.session.execute(select(RewardShopItem).order_by(RewardShopItem.enabled.desc(), RewardShopItem.price, RewardShopItem.id)).scalars().all()
    return render_template_string(SHOP_PAGE, items=items, csrf_token=session.get("csrf_token", ""), kinds=KINDS.items())


@dashboard_bp.post("/shop/create")
@owner_required
def shop_create():
    _require_csrf()
    try:
        key, title, description, item_type, price, role_id, duration = _read_product_form()
        if db.session.execute(select(RewardShopItem.id).where(RewardShopItem.key == key)).scalar_one_or_none():
            flash("Bu ürün anahtarı zaten var. Farklı bir anahtar seç.")
            return redirect(url_for("dashboard.shop_index"))
        item = RewardShopItem(key=key, title=title, description=description, item_type=item_type, price=price, discord_role_id=role_id, duration_days=duration, enabled=True)
        db.session.add(item)
        db.session.add(AuditLog(actor_discord_id=str(session["discord_id"]), action="dashboard.shop_created", target_type="shop_item", target_id=key, details={"price": price, "type": item_type}, success=True))
        db.session.commit()
        flash(f"“{title}” mağazaya eklendi.")
    except ValueError as exc:
        db.session.rollback()
        flash(str(exc))
    except Exception:
        db.session.rollback()
        log.exception("Dashboard shop item create failed")
        flash("Ürün kaydedilemedi. Panel günlüklerini kontrol et.")
    return redirect(url_for("dashboard.shop_index"))


@dashboard_bp.post("/shop/<int:item_id>/update")
@owner_required
def shop_update(item_id):
    _require_csrf()
    item = db.session.get(RewardShopItem, item_id)
    if not item:
        flash("Ürün bulunamadı.")
        return redirect(url_for("dashboard.shop_index"))
    try:
        _, title, description, item_type, price, role_id, duration = _read_product_form()
        item.title = title
        item.description = description
        item.item_type = item_type
        item.price = price
        item.discord_role_id = role_id
        item.duration_days = duration
        item.enabled = request.form.get("enabled") == "yes"
        db.session.add(AuditLog(actor_discord_id=str(session["discord_id"]), action="dashboard.shop_updated", target_type="shop_item", target_id=item.key, details={"price": price, "type": item_type, "enabled": item.enabled}, success=True))
        db.session.commit()
        flash(f"“{title}” ürünü güncellendi.")
    except ValueError as exc:
        db.session.rollback()
        flash(str(exc))
    except Exception:
        db.session.rollback()
        log.exception("Dashboard shop item update failed")
        flash("Ürün güncellenemedi. Panel günlüklerini kontrol et.")
    return redirect(url_for("dashboard.shop_index"))


@dashboard_bp.post("/shop/<int:item_id>/hide")
@owner_required
def shop_delete(item_id):
    _require_csrf()
    item = db.session.get(RewardShopItem, item_id)
    if not item:
        flash("Ürün bulunamadı.")
        return redirect(url_for("dashboard.shop_index"))
    item.enabled = False
    db.session.add(AuditLog(actor_discord_id=str(session["discord_id"]), action="dashboard.shop_hidden", target_type="shop_item", target_id=item.key, details={"title": item.title}, success=True))
    db.session.commit()
    flash(f"“{item.title}” mağazadan gizlendi. Eski satın alma kayıtları korundu.")
    return redirect(url_for("dashboard.shop_index"))

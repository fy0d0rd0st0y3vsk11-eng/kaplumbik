# Kaplumbik — Mahzen Discord Botu

Kaplumbik, Mahzen Discord sunucusu için etkinlik, katılım ve puan yönetimi altyapısıdır.

## Mevcut altyapı

- Discord botu: `run_bot.py`
- Flask web uygulaması ve sağlık kontrolü: `app/__init__.py`
- Yönetim paneli başlangıç ekranı: `app/dashboard/routes.py`
- Etkinlik ve katılım modelleri: `app/database/event_models.py`
- Puan ve işlem kayıtları: `app/database/models.py`

## Slash komutları

Bot açılırken Discord komutlarını otomatik senkronize eder:

- `/etkinlikler` — yaklaşan etkinlikleri listeler
- `/etkinlik` — etkinlik ayrıntılarını ve katılım butonlarını gösterir
- `/kimtasarladi` — Kaplumbik tasarımcısını gösterir
- `/tanit` — seçilen üyeye Mahzen tanıtımını gösterir
- `/profil` — üye profili, puan ve rozetleri gösterir
- `/etkinlikgecmisi` — etkinlik katılım geçmişini gösterir

Komutları test sunucusunda hemen görünür yapmak için ortam değişkeni olarak `DISCORD_GUILD_ID` ekleyin. Bu değer boşsa komutlar global olarak senkronize edilir; Discord'un tüm sunuculara yayması biraz zaman alabilir.

## Yerel çalıştırma

1. Python 3.11 veya üzeri kurun.
2. Bağımlılıkları yükleyin: `pip install -r requirements.txt`
3. `.env.example` dosyasını temel alarak ortam değişkenlerini ayarlayın.
4. Discord botunu çalıştırın: `python run_bot.py`

Gizli anahtarları, Discord bot tokenını veya OAuth sırlarını kaynak koda ya da Git deposuna eklemeyin.

## Güvenlik ve panel durumu

Yönetim paneline gerçek sunucuda erişim açılmadan önce Discord OAuth2 oturumu ve yönetici/owner yetkilendirmesi uygulanmalıdır. Giriş ve yetki kontrolleri tamamlanmadan paneli herkese açık biçimde kullanmayın.

## Planlanan panel özellikleri

- Etkinlik oluşturma, düzenleme ve katılım takibi
- Katılım yönetici tarafından doğrulandıktan sonra puan ödülü
- Üye bakiyeleri, puan hareketleri ve denetim kayıtları
- Duyuru ayarları ve bot sağlık durumu
- Yönetici işlemleri için kimlik doğrulama ve yetki kontrolü


## Mahzen ortak seri sistemi (yeni geliştirme dalı)

- `/seri` — günlük hedefi, seri uzunluğunu ve telafi bekleyen günleri gösterir.
- `/serikanal` — ilerleme ve günlük özetlerin yayımlanacağı kanalı ayarlar.
- `/serikaynakkanal` — ortak sayaca katkı veren sohbet kanallarını ekler/çıkarır.
- `/seritelafi` — son telafi bekleyen günleri sunucu sahibi veya Discord Administrator yetkilisi adına telafi eder.
- `/serikatkiduzelt` — yalnızca tanımlı sunucu sahibinin, gerekçe kaydıyla katkı düzeltmesini sağlar.

Günlük hedef Europe/Istanbul saatine göre 00.00'da yenilenir; farklı gerçek üyelerden 3 mesaj hedefi vardır. Botlar/webhook'lar sayılmaz, aynı üye günde bir kez sayılır. Katkılar ve denetim kayıtları SQL veritabanında tutulur. Bu özellik şu anda `feature/shared-streak-system` dalında geliştirilmekte ve test edilmektedir; ana dala henüz alınmamıştır.


## Render production checklist

- Deploy as a normal Render Web Service using the repository's existing start command; do not commit tokens or OAuth secrets.
- Set `APP_ENV=production`, `SECRET_KEY`, `DISCORD_TOKEN`, `OWNER_DISCORD_ID`, `DISCORD_CLIENT_ID`, `DISCORD_CLIENT_SECRET`, and the exact public `DISCORD_REDIRECT_URI`.
- Set `DATABASE_URL` to a persistent PostgreSQL service. The free web service filesystem is not durable; do not rely on local SQLite for production state.
- Set `OPENROUTER_API_KEY` and `OPENROUTER_MODEL` only if AI is enabled. Keep secrets in Render environment settings, never in Git.
- Enable the Discord Message Content and Server Members intents only if needed in the Discord Developer Portal. Invite the bot with applications.commands and required bot permissions.
- Verify OAuth redirect URL, database persistence, command registration, channel permissions, and restore from backup before inviting members to rely on the bot.

## Community commands added on feature branch

- `/oyunprofil`, `/oyunarkadasi`: opt-in member game profile and matching.
- `/anket`: button-based polls with one mutable vote per member.
- `/onerigonder`, `/onerioyla`, `/oneridurum`: suggestion intake, cooldown, voting and admin status flow.
- `/gorevler`, `/goreval`: weekly personal/shared quest progress and idempotent reward claim.
- `/dukkan`, `/dukkanurunekle`, `/dukkanal`, `/koleksiyon`: reward shop and member collection.
- `/modulizin`: owner-only role/module permission configuration record.

The module-permission record is not a substitute for enforcing permissions on every dashboard route and command. Those enforcement paths and remaining planned dashboard features must be reviewed before production rollout.


## Backup and restore

- The bot creates compressed database snapshots automatically and retains local snapshots for 30 days; owner-only slash commands are `/yedekle` and `/yedekdurum`.
- Render free Web Service storage is ephemeral. For durable 30-day backups, configure an S3-compatible bucket with `BACKUP_S3_ENDPOINT`, `BACKUP_S3_BUCKET`, `BACKUP_S3_ACCESS_KEY`, and `BACKUP_S3_SECRET_KEY`, or point `BACKUP_DIR` at a persistent mounted directory on a host that supports one.
- A restore helper exists for controlled maintenance use in `app.events.backups.restore_backup(path)`; it is destructive and must only be used after a separate verified backup and a planned maintenance window. A production restore drill is still required before relying on backups.
- Dashboard owner login requires Discord OAuth plus TOTP. Configure a strong Base32 `OWNER_TOTP_SECRET` in the host's secret environment settings and add the same secret to an authenticator app. Do not put the secret in Git.

- In production, `BACKUP_ENCRYPTION_KEY` is required. Generate one with `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` and save it only in Render secret environment settings. Keep a separate secure copy; without this key, encrypted backups cannot be restored.

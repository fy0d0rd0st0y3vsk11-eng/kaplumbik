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
- `/tanit` — yönetim panelinde hazırlanmış kişi tanıtımını gösterir
- `/kendinitanit` — üye iki ayrı alana isim ve hakkında bilgisini girer; kayıt yönetici onayı bekler
- `/kisitanit` — paneldeki kişi profillerini ve onaylanmış üye tanıtımlarını listeler
- `/mahzenkomutlar` — Mahzen’e özel komutların rehberini gösterir
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

## Panel kapsamı ve kalan üretim kontrolleri

- Etkinlik oluşturma, düzenleme ve katılım takibi
- Katılım yönetici tarafından doğrulandıktan sonra puan ödülü
- Üye bakiyeleri, puan hareketleri ve denetim kayıtları
- Duyuru ayarları ve bot sağlık durumu
- Yönetici işlemleri için kimlik doğrulama ve yetki kontrolü


## Mahzen ortak seri sistemi

- `/seri` — günlük hedefi, seri uzunluğunu ve telafi bekleyen günleri gösterir.
- `/serikanal` — ilerleme ve günlük özetlerin yayımlanacağı kanalı ayarlar.
- `/serikaynakkanal` — ortak sayaca katkı veren sohbet kanallarını ekler/çıkarır.
- `/seritelafi` — son telafi bekleyen günleri sunucu sahibi veya Discord Administrator yetkilisi adına telafi eder.
- `/serikatkiduzelt` — yalnızca tanımlı sunucu sahibinin, gerekçe kaydıyla katkı düzeltmesini sağlar.

Günlük hedef Europe/Istanbul saatine göre 00.00'da yenilenir; farklı gerçek üyelerden 3 mesaj hedefi vardır. Botlar/webhook'lar sayılmaz, aynı üye günde bir kez sayılır. Katkılar ve denetim kayıtları SQL veritabanında tutulur. Bu özellik PR #2 ile `main` dalına birleştirilmiştir. Gerçek sunucuda çalışması için kanal ayarları ve gerekli Discord izinleri yapılandırılmalıdır.


## Production checklist (Fadehost)

- Deploy as a normal Fadehost Web Service using the repository's existing start command; do not commit tokens or OAuth secrets.
- Set `APP_ENV=production`, `SECRET_KEY`, `DISCORD_TOKEN`, `OWNER_DISCORD_ID`, `DISCORD_CLIENT_ID`, `DISCORD_CLIENT_SECRET`, and the exact public `DISCORD_REDIRECT_URI`.
- Set `DATABASE_URL` to a persistent PostgreSQL service. The free web service filesystem is not durable; do not rely on local SQLite for production state.
- Set `OPENROUTER_API_KEY` and `OPENROUTER_MODEL` only if AI is enabled. Keep secrets in Fadehost environment settings, never in Git.
- Enable the Discord Message Content and Server Members intents only if needed in the Discord Developer Portal. Invite the bot with applications.commands and required bot permissions.
- Verify OAuth redirect URL, database persistence, command registration, channel permissions, and restore from backup before inviting members to rely on the bot.

## Community commands

- `/oyunprofil`, `/oyunarkadasi`: opt-in member game profile and matching.
- `/anket`: button-based polls with one mutable vote per member.
- `/onerigonder`, `/onerioyla`, `/oneridurum`: suggestion intake, cooldown, voting and admin status flow.
- `/gorevler`, `/goreval`: weekly personal/shared quest progress and idempotent reward claim.
- `/dukkan`, `/dukkanurunekle`, `/dukkanal`: configurable shop listing, admin product creation, and purchases for roles, cosmetic titles, badges, and collectibles.\n- `/envanter`: list all owned shop items with their type and expiry.\n- `/unvan`: view, equip, or remove an owned cosmetic title; the active title is shown on `/profil`.\n- `/rozetler`: view purchased badge products. `/koleksiyon`: view owned collectible products. Ownership is stored in the database and survives bot restarts.
- `/modulizin`: owner-only role/module permission configuration record.

The module-permission record is not a substitute for enforcing permissions on every dashboard route and command. Those enforcement paths and remaining planned dashboard features must be reviewed before production rollout.


## Backup and restore

- The bot creates compressed database snapshots automatically and retains local snapshots for 30 days; owner-only slash commands are `/yedekle` and `/yedekdurum`.
- If the Fadehost service filesystem is ephemeral, local backups alone are not durable. For durable 30-day backups, configure an S3-compatible bucket with `BACKUP_S3_ENDPOINT`, `BACKUP_S3_BUCKET`, `BACKUP_S3_ACCESS_KEY`, and `BACKUP_S3_SECRET_KEY`, or point `BACKUP_DIR` at a persistent mounted directory on a host that supports one.
- A restore helper exists for controlled maintenance use in `app.events.backups.restore_backup(path)`; it is destructive and must only be used after a separate verified backup and a planned maintenance window. A production restore drill is still required before relying on backups.
- Dashboard owner login requires Discord OAuth plus TOTP. Configure a strong Base32 `OWNER_TOTP_SECRET` in the host's secret environment settings and add the same secret to an authenticator app. Do not put the secret in Git.

- In production, `BACKUP_ENCRYPTION_KEY` is required. Generate one with `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` and save it only in Fadehost secret environment settings. Keep a separate secure copy; without this key, encrypted backups cannot be restored.


## Expanded feature commands

### Shared streak
- `/seri`, `/serikanal`, `/serikaynakkanal`, `/seritelafi`, `/serikatkiduzelt`.
- On startup, the bot attempts to recover missed contributions from accessible configured Discord channel history. Discord history permissions and retention still limit what can be recovered.
- Successful days award the configured number of points per contributor once, using idempotent ledger keys.

### Community
- `/takvim` — next 7 days of events.
- `/anket`, `/anketsonuc`, `/anketoner` — button poll, results, or AI-suggested draft (AI draft is not published automatically).
- `/onerigonder`, `/onerioyla`, `/oneridurum` — suggestions, cooldown, voting and moderation status.
- `/oyunprofil`, `/oyunarkadasi` — opt-in profile and game buddy matching.
- `/gorevler`, `/goreval` — personal/shared weekly tasks and one-time rewards.
- `/dukkan`, `/dukkanurunekle`, `/dukkanal` — configurable rewards and purchases, including cosmetic titles, badges, and collectibles.\n- `/envanter`, `/unvan`, `/rozetler`, `/koleksiyon` — owned shop inventory, title selection, purchased badges, and collectibles.
- `/puangecmisi` — private recent point ledger.
- `/sunucuhafizaoner`, `/sunucuhafizabekleyen`, `/sunucuhafizayonet` — proposed shared server knowledge requires moderator approval.
- `/hafiziyiac`, `/hafiziyikapat`, `/hafizami`, `/hafizamitemizle` — personal AI memory is opt-in and members can view or delete their own records.
- `/izinprova`, `/modulizin` — dry-run permission report and owner-controlled module-role configuration.

### Security and operations
- `/guvenlikrolleri` — owner-only verification/restricted/helper role setup.
- `/raidkilidikaldir` — owner-only anti-raid/anti-nuke alert reset after 30 minutes without new signals.
- `/uyetimeout` — helper timeouts capped at 10 minutes; Administrator/owner can set longer durations within Discord's limit.
- `/yedekle`, `/yedekdurum` — owner-only encrypted backup controls.
- Dashboard owner access requires Discord OAuth and TOTP 2FA. Configure all environment secrets before production.

PR #2 is merged into `main`. A green GitHub Actions run confirms compile/test success for the tested commit, not a live Discord/Fadehost deployment or a guarantee that every Discord permission and external integration is configured. Perform a real test-server rollout and a verified backup restore drill before production use.


For dashboard Administrator read-only access, set `DISCORD_GUILD_ID` to the target Mahzen server ID and add the `guilds` scope to the Discord OAuth app. The configured owner remains the only account that can change critical dashboard settings and must pass TOTP. In Discord's server/channel permission settings, remove **Create Invite** from ordinary member roles if invite creation must be restricted; Kaplumbik's `/davet` command itself is admin-only but cannot override Discord's native permission system for the UI.


## Fadehost setup

Use the service's Python start command `python run_bot.py`. The process starts both the Discord bot and the Flask dashboard; the host must expose the assigned `PORT` to the web service. Do not run `run.py` as the bot start command.

Set these environment variables in Fadehost (never commit secrets):

- Required for bot + web startup: `DISCORD_TOKEN`, `APP_ENV=production`, a long random `SECRET_KEY`, and `DATABASE_URL`.
- Required to sync commands to Mahzen and create/select `#seri` from the dashboard: `DISCORD_GUILD_ID`.
- Required for owner dashboard login: `OWNER_DISCORD_ID`, `OWNER_TOTP_SECRET`, `DISCORD_CLIENT_ID`, `DISCORD_CLIENT_SECRET`, and `DISCORD_REDIRECT_URI`.
- Set `DISCORD_REDIRECT_URI` to the exact public Fadehost URL ending in `/dashboard/callback`, and add that same URL to the Discord Developer Portal OAuth2 Redirects list.
- Required for AI replies: `OPENROUTER_API_KEY`. `OPENROUTER_MODEL` is optional; the code falls back to `openai/gpt-4o-mini`.
- Required for encrypted production backups: `BACKUP_ENCRYPTION_KEY`. Keep a secure offline copy; losing it means encrypted backups cannot be decrypted.
- For durable off-host backups, set `BACKUP_S3_ENDPOINT`, `BACKUP_S3_BUCKET`, `BACKUP_S3_ACCESS_KEY`, and `BACKUP_S3_SECRET_KEY`. If Fadehost storage is not persistent, local backups alone are not durable.
- `BACKUP_DIR` and `LOG_LEVEL` are optional. Do not set `PORT` manually if Fadehost injects it; otherwise follow the host's port configuration.

### First boot checklist

1. Ensure the bot is invited to Mahzen with the required slash-command and channel permissions; enable **Message Content Intent** and **Server Members Intent** in the Discord Developer Portal.
2. Configure the persistent database before relying on points, streaks, events or profiles. `db.create_all()` creates new tables but is not a replacement for a migration if an existing table schema changes.
3. Open `/dashboard`, sign in with Discord, and finish owner TOTP verification.
4. Open **Panel kişiselleştirme → Seri kanalı** and click **Mevcut #seri kanalını seç / yoksa oluştur**. The bot needs **Manage Channels** to create the channel. Then set one or more source chat channel IDs and save. The streak starts only after both output and source channels are configured.
5. Test an event, a point transaction, an AI reply, a daily streak contribution and the backup status. Confirm the bot can read message history in each configured source channel.
6. Test a database backup and restore procedure before relying on production data.

A green automated test run does not prove the external host, OAuth settings, Discord permissions, AI provider or database persistence are configured correctly.

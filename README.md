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

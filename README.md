# Kaplumbik — Mahzen Discord Botu

Kaplumbik, Mahzen Discord sunucusu için etkinlik, katılım ve puan yönetimi altyapısıdır.

## Mevcut altyapı

- Discord botu: `run_bot.py`
- Flask web uygulaması ve sağlık kontrolü: `app/__init__.py`
- Yönetim paneli başlangıç ekranı: `app/dashboard/routes.py`
- Etkinlik ve katılım modelleri: `app/database/event_models.py`
- Puan ve işlem kayıtları: `app/database/models.py`

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

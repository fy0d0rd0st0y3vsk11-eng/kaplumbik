
from flask import render_template_string

from . import dashboard_bp


@dashboard_bp.get("/")
def index():
    return render_template_string(
        """
        <!doctype html>
        <html lang="tr">
        <head>
            <meta charset="utf-8">
            <meta name="viewport"
                  content="width=device-width, initial-scale=1">
            <title>Kaplumbik Yönetim Paneli</title>
        </head>
        <body>
            <main>
                <h1>🐢 Kaplumbik</h1>
                <p>Mahzen yönetim paneli altyapısı hazırlanıyor.</p>
                <p>Bu ekran henüz giriş sistemiyle korunmuyor.</p>
            </main>
        </body>
        </html>
        """
    )
  

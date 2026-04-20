import os
import re
import logging
from datetime import datetime
import requests
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
NOTION_TOKEN = os.environ["NOTION_TOKEN"]
NOTION_ISLEM_DB = os.environ["NOTION_ISLEM_DB"]
NOTION_PORTFOY_DB = os.environ["NOTION_PORTFOY_DB"]

logging.basicConfig(level=logging.INFO)

NOTION_HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json"
}


# ── Portföyde hisseyi bul ──────────────────────────────────────────
def portfoy_bul(hisse):
    """Portföy DB'de hisseyi arar. Bulursa (page_id, lot, avg, total) döner."""
    url = f"https://api.notion.com/v1/databases/{NOTION_PORTFOY_DB}/query"
    data = {
        "filter": {
            "property": "Hisse",
            "title": {"equals": hisse.upper()}
        }
    }
    r = requests.post(url, headers=NOTION_HEADERS, json=data)
    results = r.json().get("results", [])
    if not results:
        return None
    page = results[0]
    props = page["properties"]
    return {
        "page_id": page["id"],
        "lot": props["Toplam Lot"]["number"] or 0,
        "avg": props["Ortalama Maliyet"]["number"] or 0,
        "total": props["Toplam Yatırım"]["number"] or 0,
    }


# ── Portföyü güncelle veya oluştur ────────────────────────────────
def portfoy_guncelle(hisse, yeni_lot, yeni_avg, yeni_total, page_id=None):
    tarih = datetime.today().strftime("%Y-%m-%d")
    properties = {
        "Hisse": {"title": [{"text": {"content": hisse.upper()}}]},
        "Toplam Lot": {"number": round(yeni_lot, 4)},
        "Ortalama Maliyet": {"number": round(yeni_avg, 4)},
        "Toplam Yatırım": {"number": round(yeni_total, 2)},
        "Son Güncelleme": {"date": {"start": tarih}},
    }
    if page_id:
        r = requests.patch(
            f"https://api.notion.com/v1/pages/{page_id}",
            headers=NOTION_HEADERS,
            json={"properties": properties}
        )
    else:
        r = requests.post(
            "https://api.notion.com/v1/pages",
            headers=NOTION_HEADERS,
            json={"parent": {"database_id": NOTION_PORTFOY_DB}, "properties": properties}
        )
    return r.status_code in (200, 201)


# ── İşlemi Borsa 2026'ya kaydet ───────────────────────────────────
def islem_kaydet(hisse, quantity, price, profit_loss=None):
    properties = {
        "Stock Name": {"title": [{"text": {"content": hisse.upper()}}]},
        "Price": {"number": price},
        "Quantity": {"number": quantity},
        "Date": {"date": {"start": datetime.today().strftime("%Y-%m-%d")}},
    }
    if profit_loss is not None:
        properties["Profit/Loss"] = {"number": profit_loss}
    r = requests.post(
        "https://api.notion.com/v1/pages",
        headers=NOTION_HEADERS,
        json={"parent": {"database_id": NOTION_ISLEM_DB}, "properties": properties}
    )
    return r.status_code in (200, 201)


# ── Mesajı parse et ───────────────────────────────────────────────
def mesaj_parse(text):
    text = text.strip()
    parts = text.split()
    if len(parts) < 3:
        return None

    stock = parts[0].upper()
    sayilar = re.findall(r'[-+]?\d+(?:[.,]\d+)?', text)
    if len(sayilar) < 2:
        return None

    quantity = float(sayilar[0].replace(',', '.'))
    price = float(sayilar[1].replace(',', '.'))
    profit_loss = float(sayilar[2].replace(',', '.')) if len(sayilar) >= 3 else None

    if any(k in text.lower() for k in ['sattım', 'sat', 'sell', 'sold']):
        quantity = -abs(quantity)
    else:
        quantity = abs(quantity)

    return {"stock": stock, "quantity": quantity, "price": price, "profit_loss": profit_loss}


# ── Telegram handler ──────────────────────────────────────────────
async def mesaj_isle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    parsed = mesaj_parse(text)

    if not parsed:
        await update.message.reply_text(
            "❌ Anlayamadım. Şu formatta yaz:\n"
            "THYAO 5 adet 200 TL aldım\n"
            "THYAO 3 adet 185 TL sattım"
        )
        return

    hisse = parsed["stock"]
    quantity = parsed["quantity"]
    price = parsed["price"]
    is_alis = quantity > 0

    # Mevcut portföyü çek
    mevcut = portfoy_bul(hisse)

    if is_alis:
        # Alım: ağırlıklı ortalama hesapla
        eski_lot = mevcut["lot"] if mevcut else 0
        eski_avg = mevcut["avg"] if mevcut else 0
        yeni_lot = eski_lot + quantity
        yeni_avg = ((eski_lot * eski_avg) + (quantity * price)) / yeni_lot
        yeni_total = yeni_lot * yeni_avg
    else:
        # Satım: lot azalt, ortalama maliyet değişmez
        eski_lot = mevcut["lot"] if mevcut else 0
        eski_avg = mevcut["avg"] if mevcut else price
        yeni_lot = eski_lot + quantity  # quantity zaten negatif
        yeni_avg = eski_avg
        yeni_total = max(0, yeni_lot * yeni_avg)

    page_id = mevcut["page_id"] if mevcut else None
    portfoy_ok = portfoy_guncelle(hisse, yeni_lot, yeni_avg, yeni_total, page_id)
    islem_ok = islem_kaydet(hisse, quantity, price, parsed["profit_loss"])

    if portfoy_ok and islem_ok:
        islem_adi = "📈 Alım" if is_alis else "📉 Satım"
        await update.message.reply_text(
            f"✅ Kaydedildi!\n\n"
            f"{islem_adi}: {hisse}\n"
            f"Adet: {abs(quantity)}\n"
            f"Fiyat: {price} ₺\n"
            f"─────────────\n"
            f"📊 Portföy Özeti:\n"
            f"Toplam Lot: {round(yeni_lot, 4)}\n"
            f"Ort. Maliyet: {round(yeni_avg, 2)} ₺\n"
            f"Toplam Yatırım: {round(yeni_total, 2)} ₺"
            + (f"\nKar/Zarar: {parsed['profit_loss']} ₺" if parsed["profit_loss"] else "")
        )
    else:
        await update.message.reply_text("❌ Notion'a kaydedilemedi, token/DB ID'yi kontrol et.")


if __name__ == "__main__":
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, mesaj_isle))
    print("Bot çalışıyor...")
    app.run_polling()

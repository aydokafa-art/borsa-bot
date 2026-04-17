import os
import re
import logging
from datetime import datetime
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes
import requests

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
NOTION_TOKEN = os.environ["NOTION_TOKEN"]
NOTION_DATABASE_ID = os.environ["NOTION_DATABASE_ID"]

logging.basicConfig(level=logging.INFO)


def notion_ekle(stock_name, quantity, price, profit_loss=None, position=None):
    url = "https://api.notion.com/v1/pages"
    headers = {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json"
    }
    properties = {
        "Stock Name": {
            "title": [{"text": {"content": stock_name.upper()}}]
        },
        "Price": {"number": price},
        "Quantity": {"number": quantity},
        "Date": {"date": {"start": datetime.today().strftime("%Y-%m-%d")}}
    }
    if profit_loss is not None:
        properties["Profit/Loss"] = {"number": profit_loss}
    if position is not None:
        properties["Position"] = {"number": position}

    data = {
        "parent": {"database_id": NOTION_DATABASE_ID},
        "properties": properties
    }
    response = requests.post(url, headers=headers, json=data)
    return response.status_code == 200


def mesaj_parse(text):
    """
    Desteklenen formatlar:
    - THYAO 5 adet 200 TL aldım   → quantity: +5
    - THYAO 5 adet 200 TL sattım  → quantity: -5
    - THYAO 5 200                  → kısa format
    - THYAO 5 adet 200 TL kar/zarar: 150 TL
    """
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

    return {
        "stock": stock,
        "quantity": quantity,
        "price": price,
        "profit_loss": profit_loss
    }


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

    basari = notion_ekle(
        stock_name=parsed["stock"],
        quantity=parsed["quantity"],
        price=parsed["price"],
        profit_loss=parsed["profit_loss"]
    )

    if basari:
        islem = "📈 Alım" if parsed["quantity"] > 0 else "📉 Satım"
        await update.message.reply_text(
            f"✅ Notion'a kaydedildi!\n\n"
            f"{islem}: {parsed['stock']}\n"
            f"Adet: {abs(parsed['quantity'])}\n"
            f"Fiyat: {parsed['price']} ₺"
            + (f"\nKar/Zarar: {parsed['profit_loss']} ₺" if parsed['profit_loss'] else "")
        )
    else:
        await update.message.reply_text("❌ Notion'a kaydedilemedi. Token veya database ID'yi kontrol et.")


if __name__ == "__main__":
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, mesaj_isle))
    print("Bot çalışıyor...")
    app.run_polling()

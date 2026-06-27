"""
Price Tracker - Perfumerías
============================
Sigue precios de productos en distintas tiendas (Parfumerie, Juleriaque,
Beauty24, Perfumerías Rouge, y cualquier otra que agregues) y avisa por
Telegram cuando detecta una baja de precio.

Cómo agregar / sacar productos:
  -> Editá products.json. Cada producto es {"name": "...", "url": "..."}.
     No hace falta tocar nada más: el dominio de la URL define
     automáticamente cómo se lee el precio.

Variables de entorno necesarias:
  TELEGRAM_BOT_TOKEN  -> token que te da @BotFather
  TELEGRAM_CHAT_ID    -> tu chat id (ver README.md)
  DEBUG=1             -> (opcional) imprime TODOS los precios candidatos
                         que encontró en cada página, para calibrar.
"""

import json
import os
import re
import sys
import time
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

PRODUCTS_FILE = "products.json"
HISTORY_FILE = "price_history.json"

# Dominios que necesitan un navegador real (JS) para mostrar el precio.
BROWSER_DOMAINS = {"juleriaque.com.ar"}

# Palabras que descalifican un precio candidato (cuotas, no el precio real)
EXCLUDE_KEYWORDS = ["cuota", "interes", "interés", "mensual", "instalment", "installment", "x12", "x 12"]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "es-AR,es;q=0.9,en;q=0.8",
}

DEBUG = os.environ.get("DEBUG") == "1"


def log_debug(msg):
    if DEBUG:
        print(f"[DEBUG] {msg}")


def parse_price_text(raw):
    """Convierte '$ 297.000' o '297.000,50' en un float: 297000.0 / 297000.5"""
    raw = raw.strip()
    raw = re.sub(r"[^\d.,]", "", raw)
    if not raw:
        return None
    # Formato AR: punto = miles, coma = decimales
    if "," in raw and "." in raw:
        raw = raw.replace(".", "").replace(",", ".")
    elif "," in raw:
        raw = raw.replace(",", ".")
    else:
        raw = raw.replace(".", "")
    try:
        return float(raw)
    except ValueError:
        return None


def extract_price_from_meta(soup):
    """Magento y muchos sitios traen <meta property="product:price:amount" content="X">"""
    tag = soup.find("meta", attrs={"property": "product:price:amount"})
    if tag and tag.get("content"):
        try:
            value = float(tag["content"])
            if value > 0:
                return value
        except ValueError:
            pass
    return None


def extract_price_candidates(soup):
    """Busca cualquier elemento cuya clase contenga 'price' y tenga un '$ NNN'."""
    candidates = []
    for tag in soup.find_all(class_=True):
        classes = " ".join(tag.get("class", [])).lower()
        if "price" not in classes:
            continue
        text = tag.get_text(strip=True)
        if "$" not in text:
            continue
        match = re.search(r"\$\s*([\d.,]+)", text)
        if not match:
            continue
        value = parse_price_text(match.group(1))
        if value is None or value < 100:  # filtra basura / cuotas en cantidad
            continue
        excluded = any(kw in classes or kw in text.lower() for kw in EXCLUDE_KEYWORDS)
        candidates.append({"value": value, "classes": classes, "text": text, "excluded": excluded})
    return candidates


def choose_best_price(candidates):
    """De los candidatos encontrados, elige el que más probablemente es el precio real."""
    usable = [c for c in candidates if not c["excluded"]]
    pool = usable if usable else candidates
    if not pool:
        return None
    # Si hay precio de lista + precio con descuento, el real/vigente suele ser el menor.
    return min(pool, key=lambda c: c["value"])["value"]


def fetch_static(url):
    resp = requests.get(url, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    return BeautifulSoup(resp.text, "html.parser")


def fetch_with_browser(url):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(user_agent=HEADERS["User-Agent"])
        page.goto(url, timeout=30000)
        try:
            page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass
        page.wait_for_timeout(2000)  # margen extra para que hidrate el precio
        html = page.content()
        browser.close()
    return BeautifulSoup(html, "html.parser")


def get_price(url):
    domain = re.sub(r"^https?://(www\.)?", "", url).split("/")[0]

    needs_browser = any(d in domain for d in BROWSER_DOMAINS)
    soup = fetch_with_browser(url) if needs_browser else fetch_static(url)

    price = extract_price_from_meta(soup)
    if price:
        log_debug(f"{url} -> precio por meta tag: {price}")
        return price

    candidates = extract_price_candidates(soup)
    if DEBUG:
        for c in candidates:
            log_debug(f"  candidato: ${c['value']} | excluido={c['excluded']} | clases='{c['classes'][:60]}'")

    price = choose_best_price(candidates)
    if price is None:
        log_debug(f"{url} -> NO se encontró precio")
    return price


def load_json(path, default):
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return default


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def send_telegram(message):
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print("[WARN] Falta TELEGRAM_BOT_TOKEN o TELEGRAM_CHAT_ID, no se pudo avisar.")
        print(message)
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        requests.post(url, data={"chat_id": chat_id, "text": message, "parse_mode": "HTML"}, timeout=15)
    except Exception as e:
        print(f"[WARN] No se pudo enviar Telegram: {e}")


def main():
    products = load_json(PRODUCTS_FILE, [])
    history = load_json(HISTORY_FILE, {})

    if not products:
        print("No hay productos en products.json")
        return

    now = datetime.now(timezone.utc).isoformat()
    changed = False

    for product in products:
        name = product["name"]
        url = product["url"]
        print(f"Chequeando: {name} ...")

        try:
            price = get_price(url)
        except Exception as e:
            print(f"  [ERROR] No se pudo obtener el precio: {e}")
            continue

        if price is None:
            print("  [ERROR] No se encontró precio en la página. "
                  "Probá corriendo con DEBUG=1 para ver qué candidatos hay.")
            continue

        entry = history.get(url, {"name": name, "last_price": None, "history": []})
        last_price = entry["last_price"]

        print(f"  Precio actual: ${price:,.0f}".replace(",", "."))

        if last_price is not None and price != last_price:
            diff = price - last_price
            pct = (diff / last_price) * 100
            arrow = "🔻 BAJÓ" if diff < 0 else "🔺 SUBIÓ"
            msg = (
                f"{arrow} de precio\n"
                f"<b>{name}</b>\n"
                f"Antes: ${last_price:,.0f}\n".replace(",", ".") +
                f"Ahora: ${price:,.0f} ({pct:+.1f}%)\n".replace(",", ".") +
                f"{url}"
            )
            print(f"  {arrow}: {last_price} -> {price}")
            send_telegram(msg)

        entry["name"] = name
        entry["last_price"] = price
        entry["history"].append({"date": now, "price": price})
        entry["history"] = entry["history"][-200:]  # no dejar crecer infinito
        history[url] = entry
        changed = True

        time.sleep(1.5)  # ser educado con los servidores

    if changed:
        save_json(HISTORY_FILE, history)
        print("Historial actualizado.")


if __name__ == "__main__":
    main()
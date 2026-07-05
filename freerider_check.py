#!/usr/bin/env python3
"""
Hertz Freerider DIAGNOS
=======================
Denna version bokar inget och matchar inga orter. Den laddar sajten,
listar alla nätverksanrop den ser, dumpar ett smakprov av varje
JSON-svar och skriver ut sidans synliga text. Syftet är att visa
exakt hur bilarna hämtas så att den riktiga versionen kan lagas.
"""

import json
from playwright.sync_api import sync_playwright

SIDOR = [
    "https://www.hertzfreerider.se/sv-se/",
    "https://www.hertzfreerider.se/",
]


def kort(s, n=800):
    s = str(s)
    return s if len(s) <= n else s[:n] + " ...[kapat]"


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(locale="sv-SE")

        sedda_url = []

        def pa_svar(response):
            try:
                ct = response.headers.get("content-type", "")
                url = response.url
                if any(x in ct for x in ("json", "javascript")) or \
                   any(url.endswith(e) for e in (".json",)):
                    sedda_url.append((url, ct))
                    if "json" in ct:
                        try:
                            data = response.json()
                            print(f"\n=== JSON-SVAR: {url}")
                            print(f"    content-type: {ct}")
                            print("    innehåll: " + kort(json.dumps(data, ensure_ascii=False)))
                        except Exception:
                            pass
            except Exception:
                pass

        page.on("response", pa_svar)

        for url in SIDOR:
            print(f"\n########## LADDAR {url}")
            try:
                page.goto(url, wait_until="networkidle", timeout=60000)
                page.wait_for_timeout(6000)
            except Exception as e:
                print(f"    Kunde inte ladda: {e}")
                continue

            print(f"\n--- SIDANS TITEL: {page.title()}")
            print(f"--- SLUTLIG URL: {page.url}")

            # Lista alla länkar, kan avslöja vart bil-listan ligger
            try:
                lankar = page.eval_on_selector_all(
                    "a", "els => els.map(e => e.getAttribute('href')).filter(Boolean)"
                )
                unika = sorted(set(lankar))[:40]
                print("\n--- LÄNKAR PÅ SIDAN:")
                for l in unika:
                    print("    " + l)
            except Exception as e:
                print(f"    Kunde inte läsa länkar: {e}")

            # Dumpa synlig text
            try:
                text = page.inner_text("body", timeout=10000)
                print("\n--- SYNLIG TEXT (början):")
                print(kort(text, 1500))
            except Exception as e:
                print(f"    Kunde inte läsa text: {e}")

        print("\n########## ALLA JSON/JS-ANROP SOM SÅGS:")
        for url, ct in sedda_url:
            print(f"    [{ct}] {url}")

        browser.close()


if __name__ == "__main__":
    main()

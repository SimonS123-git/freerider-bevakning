#!/usr/bin/env python3
"""
Hertz Freerider bevakning (molnversion för GitHub Actions)

Körs en gång per anrop. GitHub Actions schemalägger körningen
var 15:e minut och skickar push till din iPhone via ntfy.

Orter anges i miljövariabeln ORTER (mellanslagsseparerade).
Ntfy-topic anges i miljövariabeln NTFY_TOPIC.
Redan sedda resor sparas i sedda.json i repot.
"""

import json
import os
import re
import sys
import unicodedata
import urllib.request
from datetime import datetime
from pathlib import Path

SEDDA_FIL = Path("sedda.json")

SIDOR = [
    "https://www.hertzfreerider.se/sv-se/",
    "https://www.hertzfreerider.se/",
]


def normalisera(s: str) -> str:
    s = unicodedata.normalize("NFKD", s.lower().strip())
    return "".join(c for c in s if not unicodedata.combining(c))


def logg(msg: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def ntfy_notis(topic: str, titel: str, text: str) -> None:
    if not topic:
        logg("NTFY_TOPIC saknas, hoppar över push.")
        return
    try:
        req = urllib.request.Request(
            f"https://ntfy.sh/{topic}",
            data=text.encode("utf-8"),
            headers={
                "Title": titel.encode("utf-8").decode("latin-1", "ignore"),
                "Priority": "high",
                "Tags": "car",
                "Click": "https://www.hertzfreerider.se/sv-se/",
            },
            method="POST",
        )
        urllib.request.urlopen(req, timeout=15)
        logg("Push skickad.")
    except Exception as e:
        logg(f"ntfy misslyckades: {e}")


FRAN_NYCKLAR = {"origin", "from", "fromlocation", "pickuplocation", "pickup",
                "departure", "departurelocation", "start", "startstation",
                "fromstation", "originstation"}
TILL_NYCKLAR = {"destination", "to", "tolocation", "dropofflocation", "dropoff",
                "arrival", "arrivallocation", "end", "endstation",
                "tostation", "destinationstation"}


def _plocka_ort(varde):
    if isinstance(varde, str) and 1 < len(varde) < 60:
        return varde.strip()
    if isinstance(varde, dict):
        for k in ("name", "city", "title", "location", "label"):
            v = varde.get(k)
            if isinstance(v, str) and 1 < len(v) < 60:
                return v.strip()
    return None


def _leta_resor_i_json(data, resultat: list) -> None:
    if isinstance(data, dict):
        fran = till = None
        for k, v in data.items():
            nk = k.lower().replace("_", "")
            if nk in FRAN_NYCKLAR and fran is None:
                fran = _plocka_ort(v)
            elif nk in TILL_NYCKLAR and till is None:
                till = _plocka_ort(v)
        if fran and till:
            datum = ""
            for k in ("startDate", "start_date", "date", "pickupDate",
                      "availableFrom", "earliestPickup"):
                if isinstance(data.get(k), str):
                    datum = data[k][:16]
                    break
            bil = ""
            for k in ("carModel", "car", "vehicleModel", "vehicle", "model",
                      "carGroup", "description"):
                v = data.get(k)
                s = v if isinstance(v, str) else _plocka_ort(v)
                if s:
                    bil = s
                    break
            resultat.append({"fran": fran, "till": till, "datum": datum, "bil": bil})
        for v in data.values():
            _leta_resor_i_json(v, resultat)
    elif isinstance(data, list):
        for v in data:
            _leta_resor_i_json(v, resultat)


def _leta_resor_i_dom(page) -> list:
    resultat = []
    try:
        text = page.inner_text("body", timeout=10000)
    except Exception:
        return resultat
    for rad in text.splitlines():
        m = re.search(
            r"([A-ZÅÄÖ][\wåäöé .()-]{1,40}?)\s*(?:→|->)\s*([A-ZÅÄÖ][\wåäöé .()-]{1,40})",
            rad,
        )
        if m:
            fran, till = m.group(1).strip(), m.group(2).strip()
            if fran.lower() != till.lower() and len(fran) > 2 and len(till) > 2:
                resultat.append({"fran": fran, "till": till, "datum": "", "bil": ""})
    return resultat


def hamta_resor() -> list:
    from playwright.sync_api import sync_playwright

    fangade: list = []

    def pa_svar(response):
        try:
            if "json" not in response.headers.get("content-type", ""):
                return
            _leta_resor_i_json(response.json(), fangade)
        except Exception:
            pass

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(locale="sv-SE")
        page.on("response", pa_svar)

        resor: list = []
        for url in SIDOR:
            try:
                page.goto(url, wait_until="networkidle", timeout=60000)
                page.wait_for_timeout(5000)
            except Exception as e:
                logg(f"Kunde inte ladda {url}: {e}")
                continue
            if fangade:
                resor = fangade
                break
            dom_resor = _leta_resor_i_dom(page)
            if dom_resor:
                resor = dom_resor
                break

        browser.close()

    unika = {}
    for r in resor:
        nyckel = f"{normalisera(r['fran'])}|{normalisera(r['till'])}|{r['datum']}"
        unika[nyckel] = r
    return list(unika.values())


def main() -> None:
    orter = os.environ.get("ORTER", "").split()
    topic = os.environ.get("NTFY_TOPIC", "").strip()

    if not orter:
        logg("Inga orter angivna. Sätt ORTER i workflow-filen.")
        sys.exit(1)

    orter_norm = [normalisera(o) for o in orter]
    logg(f"Bevakar: {', '.join(orter)}")

    try:
        sedda = set(json.loads(SEDDA_FIL.read_text()))
    except Exception:
        sedda = set()

    resor = hamta_resor()
    if not resor:
        logg("Hittade inga resor alls. Sajten kan vara tom eller ha ändrats.")
        return

    logg(f"Hittade {len(resor)} resor totalt.")

    traffar = [
        r for r in resor
        if any(o in normalisera(r["fran"]) or o in normalisera(r["till"])
               for o in orter_norm)
    ]

    nya = []
    for r in traffar:
        nyckel = f"{normalisera(r['fran'])}|{normalisera(r['till'])}|{r['datum']}"
        if nyckel not in sedda:
            sedda.add(nyckel)
            nya.append(r)

    if not traffar:
        logg("Inga bilar på dina orter just nu.")
    elif not nya:
        logg(f"{len(traffar)} träff(ar), men inga nya sedan sist.")
    else:
        for r in nya:
            detalj = " ".join(x for x in (r["datum"], r["bil"]) if x)
            text = f"{r['fran']} till {r['till']}"
            if detalj:
                text += f" ({detalj})"
            logg("NY BIL: " + text)
            ntfy_notis(topic, "Freerider: bil hittad!", text)
        SEDDA_FIL.write_text(json.dumps(sorted(sedda)[-500:]))


if __name__ == "__main__":
    main()

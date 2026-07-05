#!/usr/bin/env python3
"""
Hertz Freerider bevakning
=========================
Hämtar hertzfreerider.se öppna API direkt (ingen inloggning, ingen
webbläsare) och skickar push till din iPhone via ntfy när en bil
dyker upp på en bevakad sträcka.

Två sätt att bevaka, styrs av miljövariabler i workflow-filen:

  PAR   Bevaka sträckor mellan två orter, båda riktningarna.
        Exempel:  "Stockholm-Östersund"
        Flera par separeras med komma:
                  "Stockholm-Östersund, Stockholm-Åre"

  ORTER Bevaka allt som rör en ort (valfri riktning).
        Exempel:  "Åre Östersund"

Har du satt PAR används det. Annars används ORTER.
NTFY_TOPIC anges som secret i GitHub.
"""

import json
import os
import sys
import unicodedata
import urllib.request
from datetime import datetime
from pathlib import Path

API_URL = "https://www.hertzfreerider.se/api/transport-routes/?country=SWEDEN"
SEDDA_FIL = Path("sedda.json")


def normalisera(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s).lower().strip())
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
        logg("Push skickad: " + text)
    except Exception as e:
        logg(f"ntfy misslyckades: {e}")


def hamta_api() -> list:
    req = urllib.request.Request(
        API_URL,
        headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) "
                          "Chrome/124.0 Safari/537.36",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def hitta_datum(route: dict) -> str:
    for k in ("availableFrom", "earliestPickupDate", "pickupDate",
              "startDate", "fromDate", "earliestPickup", "date"):
        v = route.get(k)
        if isinstance(v, str) and v:
            return v[:10]
    return ""


def hitta_bil(route: dict) -> str:
    for k in ("carModel", "carDescription", "vehicleModel", "model",
              "car", "vehicle", "description"):
        v = route.get(k)
        if isinstance(v, str) and v:
            return v
    return ""


def parsa_par(par_text: str) -> list:
    """'Stockholm-Östersund, Stockholm-Åre' -> [(a,b), (a,b)] normaliserat."""
    par = []
    for bit in par_text.split(","):
        bit = bit.strip()
        if not bit:
            continue
        if "-" in bit:
            a, b = bit.split("-", 1)
            par.append((normalisera(a), normalisera(b)))
    return par


def matchar_par(fran: str, till: str, par: list) -> bool:
    f, t = normalisera(fran), normalisera(till)
    for a, b in par:
        if (a in f and b in t) or (a in t and b in f):
            return True
    return False


def matchar_ort(fran: str, till: str, orter: list) -> bool:
    f, t = normalisera(fran), normalisera(till)
    return any(o in f or o in t for o in orter)


def main() -> None:
    par = parsa_par(os.environ.get("PAR", ""))
    orter = [normalisera(o) for o in os.environ.get("ORTER", "").split()]
    topic = os.environ.get("NTFY_TOPIC", "").strip()

    if not par and not orter:
        logg("Varken PAR eller ORTER angivet. Sätt en av dem i workflow-filen.")
        sys.exit(1)

    if par:
        logg("Bevakar sträckor (båda hållen): " +
             ", ".join(f"{a}<->{b}" for a, b in par))
    else:
        logg("Bevakar orter: " + ", ".join(orter))

    try:
        sedda = set(json.loads(SEDDA_FIL.read_text()))
    except Exception:
        sedda = set()

    try:
        grupper = hamta_api()
    except Exception as e:
        logg(f"Kunde inte hämta API: {e}")
        return

    logg(f"Hämtade {len(grupper)} sträckor från Freerider.")

    nya_notiser = 0
    for g in grupper:
        fran = g.get("pickupLocationName", "")
        till = g.get("returnLocationName", "")
        if not fran or not till:
            continue

        traff = matchar_par(fran, till, par) if par else matchar_ort(fran, till, orter)
        if not traff:
            continue

        routes = g.get("routes", []) or [{}]
        nya_i_grupp = []
        for route in routes:
            rid = route.get("id") or route.get("transportOfferId")
            nyckel = f"{normalisera(fran)}|{normalisera(till)}|{rid}"
            if nyckel not in sedda:
                sedda.add(nyckel)
                nya_i_grupp.append(route)

        if nya_i_grupp:
            r0 = nya_i_grupp[0]
            detalj = " ".join(x for x in (hitta_datum(r0), hitta_bil(r0)) if x)
            antal = f" ({len(nya_i_grupp)} st)" if len(nya_i_grupp) > 1 else ""
            text = f"{fran} till {till}{antal}"
            if detalj:
                text += f". {detalj}"
            logg("NY BIL: " + text)
            ntfy_notis(topic, "Freerider: bil hittad!", text)
            nya_notiser += 1

    if nya_notiser == 0:
        logg("Inga nya bilar på dina bevakade sträckor.")

    try:
        SEDDA_FIL.write_text(json.dumps(sorted(sedda)[-1000:]))
    except Exception as e:
        logg(f"Kunde inte spara sedda.json: {e}")


if __name__ == "__main__":
    main()

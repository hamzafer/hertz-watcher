#!/usr/bin/env python3
"""
Hertz Freerider corridor poller.

Runs once per invocation. Drive via cron (every minute).
Fetches the Hertz Freerider Norway listings, applies a regex geo-filter for
Trondheim->Oslo cars covering 23-26 May 2026, dedups via seen.txt, sends a
Telegram alert on any new match, and appends every poll to log.jsonl.

Env vars (required):
  TELEGRAM_BOT_TOKEN
  TELEGRAM_CHAT_ID

Env vars (optional):
  HERTZ_DATA_DIR (default: directory containing this script)
"""
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("HERTZ_DATA_DIR", str(SCRIPT_DIR)))
LOG_FILE = DATA_DIR / "log.jsonl"
SEEN_FILE = DATA_DIR / "seen.txt"

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

PICK_RE = re.compile(
    r"\b(TRONDHEIM|VAERNES|VÆRNES|STJORDAL|STJØRDAL|ORKANGER|ORKDAL|MELHUS|"
    r"STEINKJER|LEVANGER|VERDAL|ROROS|RØROS|OPPDAL)\b",
    re.IGNORECASE,
)
DROP_RE = re.compile(
    r"\b(OSLO|GARDERMOEN|LILLESTROM|LILLESTRØM|ASKER|SANDVIKA|BAERUM|BÆRUM|"
    r"DRAMMEN|LORENSKOG|LØRENSKOG|JESSHEIM|HAMAR|LILLEHAMMER|GJOVIK|GJØVIK)\b",
    re.IGNORECASE,
)

WIN_PICKUP_LATEST = "2026-05-23T23:59:59"
WIN_RETURN_EARLIEST = "2026-05-26T00:00:00"

URL = "https://www.hertzfreerider.no/api/transport-routes/?country=NORWAY"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9,nb;q=0.8",
    "Referer": "https://www.hertzfreerider.no/no-no/",
}


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def log(entry):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def fetch():
    req = urllib.request.Request(URL, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return resp.status, json.load(resp)
    except urllib.error.HTTPError as e:
        return e.code, None
    except Exception as e:
        return 0, f"exception: {e}"


def send_telegram(text):
    if not BOT_TOKEN or not CHAT_ID:
        return False, "missing-credentials"
    api = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = urllib.parse.urlencode(
        {
            "chat_id": CHAT_ID,
            "text": text,
            "disable_web_page_preview": "true",
        }
    ).encode()
    try:
        with urllib.request.urlopen(api, data=payload, timeout=10) as resp:
            return True, json.load(resp)
    except urllib.error.HTTPError as e:
        try:
            return False, json.load(e)
        except Exception:
            return False, f"http {e.code}"
    except Exception as e:
        return False, f"exception: {e}"


def load_seen():
    if not SEEN_FILE.exists():
        return set()
    return set(SEEN_FILE.read_text(encoding="utf-8").splitlines())


def mark_seen(ids):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with SEEN_FILE.open("a", encoding="utf-8") as f:
        for i in ids:
            f.write(f"{i}\n")


def fmt_match(m):
    return (
        f"{m['pickup']} → {m['return']}\n"
        f"  {m['car']}\n"
        f"  avail {m['available']} · return by {m['latest_return']}"
    )


def main():
    ts = utc_now()
    status, data = fetch()

    if status == 429:
        log({"ts": ts, "status": "rate_limited"})
        return
    if status != 200 or not isinstance(data, list):
        log({"ts": ts, "status": "fetch_error", "http_status": status, "body": data if isinstance(data, str) else None})
        return

    routes = []
    for g in data:
        for r in g.get("routes", []):
            pu = r.get("pickupLocation") or {}
            rl = r.get("returnLocation") or {}
            pickup = f"{pu.get('name','')} {pu.get('city','')}".strip()
            ret = f"{rl.get('name','')} {rl.get('city','')}".strip()
            routes.append(
                {
                    "id": r.get("id"),
                    "pickup": pickup,
                    "return": ret,
                    "car": r.get("carModel"),
                    "available": r.get("availableAt"),
                    "latest_return": r.get("latestReturn"),
                    "distance_km": r.get("distance"),
                }
            )

    seen = load_seen()
    matches = []
    for r in routes:
        geo = PICK_RE.search(r["pickup"] or "") and DROP_RE.search(r["return"] or "")
        avail = r.get("available") or ""
        lret = r.get("latest_return") or ""
        dates_ok = avail <= WIN_PICKUP_LATEST and lret >= WIN_RETURN_EARLIEST
        if geo and dates_ok and str(r["id"]) not in seen:
            matches.append(r)

    log({"ts": ts, "total": len(routes), "new_matches": len(matches), "routes": routes})

    if not matches:
        return

    lines = [
        f"🚨 BOOK NOW — {len(matches)} Hertz corridor match(es) for 23-26 May 2026!",
        "",
    ]
    for m in matches:
        lines.append(fmt_match(m))
        lines.append("")
    lines.append("Book: https://www.hertzfreerider.no/no-no/")
    msg = "\n".join(lines).rstrip()

    ok, resp = send_telegram(msg)
    log(
        {
            "ts": utc_now(),
            "status": "notified" if ok else "telegram_error",
            "matches": [m["id"] for m in matches],
            "resp": resp,
        }
    )
    if ok:
        mark_seen([m["id"] for m in matches])


if __name__ == "__main__":
    main()

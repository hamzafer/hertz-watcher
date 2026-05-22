#!/usr/bin/env python3
"""
Hjemferd.no relocation-car poller.

Runs once per invocation. Drive via cron (every 5 min recommended).
Fetches https://www.hjemferd.no/index.php?page=order, parses listings from
the server-rendered HTML, filters for Trondheim-region pickup + Oslo-corridor
return, where the pickup window covers 2026-05-23. Dedups via
hjemferd_seen.txt, sends Telegram on new match, appends every poll to
hjemferd_log.jsonl.

Env vars (required):
  TELEGRAM_BOT_TOKEN
  TELEGRAM_CHAT_ID

Env vars (optional):
  HERTZ_DATA_DIR (default: directory containing this script)
"""
import hashlib
import html
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("HERTZ_DATA_DIR", str(SCRIPT_DIR)))
LOG_FILE = DATA_DIR / "hjemferd_log.jsonl"
SEEN_FILE = DATA_DIR / "hjemferd_seen.txt"

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

PICK_RE = re.compile(
    r"(TRONDHEIM|VAERNES|VÆRNES|STJORDAL|STJØRDAL|ORKANGER|ORKDAL|MELHUS|"
    r"STEINKJER|LEVANGER|VERDAL|ROROS|RØROS|OPPDAL)",
    re.IGNORECASE,
)
DROP_RE = re.compile(
    r"(OSLO|GARDERMOEN|LILLESTROM|LILLESTRØM|ASKER|SANDVIKA|BAERUM|BÆRUM|"
    r"DRAMMEN|LORENSKOG|LØRENSKOG|JESSHEIM|HAMAR|LILLEHAMMER|GJOVIK|GJØVIK)",
    re.IGNORECASE,
)

MOVE_DATE = "2026-05-23"  # day Hamza needs to pick up

URL = "https://www.hjemferd.no/index.php?page=order"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,nb;q=0.8",
}

# Match a listing block: an order-header div with "Pickup - Drop", then
# nearby "Ledig Fra DD.MM.YYYY HH:MM" and "Må hentes før DD.MM.YYYY".
LISTING_RE = re.compile(
    r'<div class="order-header text-center">([^<]+?)\s*</div>'
    r'(.{200,3000}?)'
    r'Må hentes før</b>\s*</div>\s*<div[^>]*>([\d\.]+)</div>',
    re.DOTALL,
)
AVAIL_RE = re.compile(
    r'Ledig Fra</b>\s*</div>\s*<div[^>]*>([\d\.]+)\s*([\d:]+)?'
)


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
            return resp.status, resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, None
    except Exception as e:
        return 0, f"exception: {e}"


def parse_listings(body):
    out = []
    for m in LISTING_RE.finditer(body):
        route_text = html.unescape(m.group(1)).strip()
        if " - " in route_text:
            pickup, drop = route_text.rsplit(" - ", 1)
        else:
            pickup, drop = route_text, ""
        mid = m.group(2)
        must = m.group(3).strip()
        avm = AVAIL_RE.search(mid)
        avail_date = avm.group(1).strip() if avm else None
        avail_time = avm.group(2).strip() if (avm and avm.group(2)) else None
        if not avail_date or not must:
            continue
        listing_id = hashlib.sha1(
            f"{pickup}|{drop}|{avail_date}|{must}".encode("utf-8")
        ).hexdigest()[:12]
        out.append(
            {
                "id": listing_id,
                "route_text": route_text,
                "pickup": pickup.strip(),
                "drop": drop.strip(),
                "avail_date": avail_date,
                "avail_time": avail_time,
                "must_pickup_by": must,
            }
        )
    return out


def to_iso(dmy):
    """Convert 'DD.MM.YYYY' to 'YYYY-MM-DD' for string comparison."""
    try:
        d, m, y = dmy.split(".")
        return f"{y}-{m.zfill(2)}-{d.zfill(2)}"
    except Exception:
        return ""


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
        f"{m['pickup']} → {m['drop']}\n"
        f"  available from: {m['avail_date']} {m['avail_time'] or ''}\n"
        f"  must pick up by: {m['must_pickup_by']}"
    )


def main():
    ts = utc_now()
    status, body = fetch()

    if status != 200 or not isinstance(body, str):
        log({"ts": ts, "status": "fetch_error", "http_status": status})
        return

    listings = parse_listings(body)

    seen = load_seen()
    matches = []
    for L in listings:
        geo_ok = bool(PICK_RE.search(L["pickup"])) and bool(DROP_RE.search(L["drop"]))
        avail_iso = to_iso(L["avail_date"])
        must_iso = to_iso(L["must_pickup_by"])
        # The pickup window covers 23 May if available-from ≤ 23 May AND
        # must-pickup-by ≥ 23 May.
        window_ok = avail_iso and must_iso and avail_iso <= MOVE_DATE <= must_iso
        if geo_ok and window_ok and L["id"] not in seen:
            matches.append(L)

    log(
        {
            "ts": ts,
            "total": len(listings),
            "new_matches": len(matches),
            "listings": listings,
        }
    )

    if not matches:
        return

    lines = [
        f"🚨 HJEMFERD MATCH — {len(matches)} relocation(s) for 23 May 2026!",
        "",
    ]
    for m in matches:
        lines.append(fmt_match(m))
        lines.append("")
    lines.append("Book: https://www.hjemferd.no/index.php?page=order")
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

#!/usr/bin/env python3
"""
Forced-match smoke test for the Telegram alert path.

Runs in an isolated data dir so it does NOT touch the production seen.txt
or log.jsonl. Mocks `poller.fetch()` with a synthetic Trondheim->Oslo route
that fits the 23-26 May window. Real Telegram send goes through.

Use via:
  gh workflow run poll.yml -f test_alert=true

Local equivalent:
  TELEGRAM_BOT_TOKEN=... TELEGRAM_CHAT_ID=... python3 test_alert.py
"""
import os
import tempfile

os.environ["HERTZ_DATA_DIR"] = tempfile.mkdtemp(prefix="hertz-test-")
import poller  # noqa: E402

FAKE_ROUTE = {
    "id": 999_000,
    "pickupLocation": {"name": "TRONDHEIM LUFTHAVN", "city": "STJØRDAL"},
    "returnLocation": {"name": "OSLO LUFTHAVN", "city": "GARDERMOEN"},
    "carModel": "[E2E TEST — please ignore] VOLVO XC60 AUT",
    "availableAt": "2026-05-22T08:00:00",
    "latestReturn": "2026-05-27T18:00:00",
    "distance": 540.0,
}

poller.fetch = lambda: (200, [{"routes": [FAKE_ROUTE]}])
poller.main()
print("Test alert dispatched. Check Telegram.")

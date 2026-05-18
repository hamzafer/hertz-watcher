# Hertz Freerider corridor watcher

Polls the public Hertz Freerider Norway listings every 5 minutes (via GitHub
Actions cron). Sends a Telegram alert the moment a relocation car matches the
**Trondheim → Oslo corridor** AND covers the **23-26 May 2026** window.

## Scope

- **Window:** 23, 24, 25, 26 May 2026 (4 days). A car only matches when
  `availableAt ≤ 23 May` AND `latestReturn ≥ 26 May`.
- **Geo:** pickup must be in the Trondheim region (Trondheim, Værnes/Stjørdal,
  Orkanger, Melhus, Røros, Oppdal, etc.) and return must be in the Oslo
  corridor (Oslo, Gardermoen, Lillestrøm, Asker, Bærum, Drammen, Hamar,
  Lillehammer, etc.). See regex constants in `poller.py`.
- **Cadence:** GitHub Actions cron `*/5 * * * *` (real-world lag is typically
  1-5 min, occasionally up to 15 min during peak GitHub load).

## Files

- `poller.py` — single-shot poll: fetch listings, filter, dedup, alert.
- `test_alert.py` — forced-match smoke test for the Telegram path.
- `run.sh` — local wrapper that sources `.env` and runs `poller.py`.
- `.env.example` — template for the secrets file (used locally only).
- `.github/workflows/poll.yml` — the cron workflow.

## Local run

```bash
cp .env.example .env       # fill in real values
chmod +x run.sh
./run.sh                   # one poll, prints log entry, sends Telegram on match
```

State files (`log.jsonl`, `seen.txt`) are gitignored and stay local.

## Cloud run (GitHub Actions)

Secrets `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` are set as repo Actions
secrets. The workflow runs on the standard `ubuntu-latest` runner (free on
public repos). State (`seen.txt`) is persisted across runs via
`actions/cache` so duplicate alerts don't fire.

Manual triggers:

```bash
gh workflow run poll.yml                            # one normal poll
gh workflow run poll.yml -f test_alert=true         # forced-match smoke test
```

## Cleanup (after 27 May 2026)

The whole watcher becomes obsolete on 27 May 2026. To shut it down:

```bash
gh repo delete hamzafer/hertz-watcher --yes
```

Or, less destructively: disable the workflow under the Actions tab.

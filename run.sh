#!/bin/bash
# Wrapper: source secrets from .env, then run the poller.
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
if [ -f "$DIR/.env" ]; then
  set -a
  . "$DIR/.env"
  set +a
fi
exec /usr/bin/python3 "$DIR/poller.py"

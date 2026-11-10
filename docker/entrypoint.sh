#!/bin/sh
# serve (default) | setup | pin NAME [adult|limited] | shell | any other command
set -e
cd /app
mkdir -p /data/inbox /data/archive /data/brief /data/reports /data/exports /data/logs /data/config
case "${1:-serve}" in
  setup)  exec python onboard.py easy ;;
  pin)    shift; [ -n "$1" ] || { echo "usage: pin NAME [adult|limited]"; exit 2; }
          exec python data/auth.py set "$@" ;;
  serve)
    if [ ! -f /data/config/family.json ]; then
      echo "No household yet. Run once:  docker compose run --rm mitra setup" >&2; exit 1
    fi
    python docker/scheduler.py &
    exec python launch.py --no-browser --lan ;;
  shell)  exec sh ;;
  *)      exec "$@" ;;
esac

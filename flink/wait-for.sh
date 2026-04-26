#!/usr/bin/env bash
set -e

HOST="$1"
PORT="$2"

if [ -z "$HOST" ] || [ -z "$PORT" ]; then
  echo "usage: wait-for.sh <host> <port>"
  exit 1
fi

echo "[wait-for] waiting for ${HOST}:${PORT}"

python3 - "$HOST" "$PORT" <<'PY'
import socket
import sys
import time

host = sys.argv[1]
port = int(sys.argv[2])

while True:
    try:
        with socket.create_connection((host, port), timeout=2):
            print(f"[wait-for] {host}:{port} is ready", flush=True)
            break
    except OSError:
        time.sleep(2)
PY


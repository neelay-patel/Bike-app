#!/bin/sh
# Start Kova's backend on the host (Dockerfile). The disk is mounted at /app/data; make the folders the code
# expects on a fresh disk, then serve without an access log (the calendar feed's secret is in its address).
set -e
mkdir -p /app/data/backend/raw /app/data/osm /app/data/geo /app/data/dem /app/data/osm-cache
# Moving in (docs/hosting.md step 5): a bundle of the Mac's data uploaded to the disk is unpacked before the server
# starts, so the database is never replaced under a running server.
if [ -f /app/data/incoming.tar.gz ]; then
  echo "Unpacking the uploaded data"
  rm -f /app/data/backend/rides.sqlite3 /app/data/backend/rides.sqlite3-wal /app/data/backend/rides.sqlite3-shm
  tar -xzf /app/data/incoming.tar.gz -C /app/data
  rm /app/data/incoming.tar.gz
fi
exec python -m backend serve --host 0.0.0.0 --port "${PORT:-8080}" --no-access-log

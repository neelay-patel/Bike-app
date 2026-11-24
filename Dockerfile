# Kova's backend on a host (docs/hosting.md): the same server as on the Mac, in one small container.
# The rider data (database, ride files, map, places, elevation cache) lives on a disk mounted at /app/data, where
# the code already looks for it; nothing personal is in the image.
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

# The server's needs only (osmium builds the map, which happens on the Mac; pytest stays on the Mac).
RUN pip install "fastapi>=0.115" "uvicorn>=0.30" "httpx>=0.27" "anthropic>=2.12" "cryptography>=43"

COPY rideengine ./rideengine
COPY backend ./backend
# The card's colours and fonts (rideengine/card reads them from here).
COPY design/tokens.json ./design/tokens.json
COPY scripts/host-start.sh ./scripts/host-start.sh

EXPOSE 8080
CMD ["sh", "scripts/host-start.sh"]

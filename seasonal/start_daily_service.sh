#!/bin/sh
set -eu
BASE=/share/homes/Dsantananet/PROJETOS/GEE_Areas_Ardidas/seasonal
PRIVATE=/share/homes/Dsantananet/.config/burned_areas_gee
DOCKER=/share/CACHEDEV1_DATA/.qpkg/container-station/bin/docker
export DOCKER_CONFIG="$PRIVATE/docker"
mkdir -p "$BASE/outputs" "$BASE/logs" "$DOCKER_CONFIG"
# Safe to repeat: keep the existing service.
if "$DOCKER" ps -a --format '{{.Names}}' | grep -qx burned_areas_gee_daily; then
    "$DOCKER" start burned_areas_gee_daily
    exit 0
fi
"$DOCKER" run -d --name burned_areas_gee_daily --restart unless-stopped \
    --network container:postgis_core --memory 1g --cpus 1 \
    --log-opt max-size=10m --log-opt max-file=3 \
    --env-file "$PRIVATE/runtime.env" -e GEE_KEY_FILE=/private/service-account.json \
    -v "$PRIVATE/service-account.json:/private/service-account.json:ro" \
    -v "$BASE/outputs:/outputs" -v "$BASE:/app:ro" \
    --entrypoint python ignispyro/burned-areas-gee:1.0 -u /app/daily_runner.py

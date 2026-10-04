#!/bin/sh
set -eu
BASE=/share/homes/Dsantananet/PROJETOS/GEE_Areas_Ardidas/seasonal
PRIVATE=/share/homes/Dsantananet/.config/burned_areas_gee
DOCKER=/share/CACHEDEV1_DATA/.qpkg/container-station/bin/docker
export DOCKER_CONFIG="$PRIVATE/docker"
mkdir -p "$BASE/outputs" "$BASE/logs"
# Atomic container-name lock: an overlapping run must not start.
if "$DOCKER" ps -a --format '{{.Names}}' | grep -qx burned_areas_gee_update; then
    echo 'Existing update container; inspect its state before running again.'
    exit 1
fi
"$DOCKER" run --rm --name burned_areas_gee_update \
    --network container:postgis_core --memory 1g --cpus 1 \
    --env-file "$PRIVATE/runtime.env" \
    -e GEE_KEY_FILE=/private/service-account.json \
    -v "$PRIVATE/service-account.json:/private/service-account.json:ro" \
    -v "$BASE/outputs:/outputs" \
    -v "$BASE:/app:ro" \
    ignispyro/burned-areas-gee:1.1 \
    --year "${1:-$(date -u +%Y)}" --output /outputs \
    >> "$BASE/logs/update-$(date -u +%Y%m%d).log" 2>&1

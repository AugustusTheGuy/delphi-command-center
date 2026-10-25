#!/bin/bash
# Refresh Nextcloud trusted_domains for current Mac LAN IP (home use).
set -euo pipefail
CONTAINER="${NEXTCLOUD_CONTAINER:-nextcloud_stack-nextcloud-1}"
LAN="$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || true)"
if ! docker ps --format '{{.Names}}' | grep -qx "$CONTAINER"; then
  echo "Nextcloud container not running: $CONTAINER"
  exit 1
fi
run_occ() { docker exec -u 33 "$CONTAINER" php occ "$@"; }
run_occ config:system:set trusted_domains 0 --value=localhost
run_occ config:system:set trusted_domains 1 --value=127.0.0.1
i=2
for host in localhost 127.0.0.1 ${LAN:+"$LAN"}; do
  for port in "" :8080 :8443; do
    val="${host}${port}"
    # skip empty
    [ -z "$val" ] && continue
    run_occ config:system:set trusted_domains "$i" --value="$val" >/dev/null
    i=$((i+1))
  done
done
if [ -n "${LAN:-}" ]; then
  run_occ config:system:set overwrite.cli.url --value="https://${LAN}:8443" >/dev/null
fi
run_occ config:system:set trusted_proxies 0 --value=10.0.0.0/8 >/dev/null
run_occ config:system:set trusted_proxies 1 --value=172.16.0.0/12 >/dev/null
run_occ config:system:set trusted_proxies 2 --value=192.168.0.0/16 >/dev/null
echo "OK trusted_domains refreshed LAN=${LAN:-none}"
run_occ config:system:get trusted_domains

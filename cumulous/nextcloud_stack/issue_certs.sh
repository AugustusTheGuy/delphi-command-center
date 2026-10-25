#!/bin/bash
# Re-issue Cumulous Nextcloud TLS cert (mkcert CA + leaf) for current LAN IP.
set -euo pipefail
cd "$(dirname "$0")"
CERTS="$(pwd)/certs"
export CAROOT="${CERTS}/mkcert-ca"
mkdir -p "$CAROOT"

LAN="$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || true)"
HOST_LOCAL="$(scutil --get LocalHostName 2>/dev/null || hostname -s)"

if ! command -v mkcert >/dev/null 2>&1; then
  echo "Install mkcert: brew install mkcert"
  exit 1
fi

# Ensure CA exists
if [ ! -f "${CAROOT}/rootCA.pem" ] || [ ! -f "${CAROOT}/rootCA-key.pem" ]; then
  mkcert -install 2>/dev/null || true
fi

ARGS=(localhost 127.0.0.1 ::1 nextcloud.local cumulous.local cumulous-nextcloud.local)
[ -n "${LAN:-}" ] && ARGS+=("$LAN")
[ -n "${HOST_LOCAL:-}" ] && ARGS+=("${HOST_LOCAL}.local")

echo "Issuing cert for: ${ARGS[*]}"
mkcert -cert-file "${CERTS}/cert.pem" -key-file "${CERTS}/key.pem" "${ARGS[@]}"
cp "${CAROOT}/rootCA.pem" "${CERTS}/ca.pem"
cat "${CERTS}/cert.pem" "${CERTS}/ca.pem" > "${CERTS}/fullchain.pem"
chmod 644 "${CERTS}/cert.pem" "${CERTS}/ca.pem" "${CERTS}/fullchain.pem"
chmod 600 "${CERTS}/key.pem"

mkdir -p "$HOME/.cumulous"
cp "${CERTS}/ca.pem" "$HOME/.cumulous/nextcloud_ca.pem"
chmod 600 "$HOME/.cumulous/nextcloud_ca.pem"

openssl verify -CAfile "${CERTS}/ca.pem" "${CERTS}/cert.pem"
echo "OK — restart Caddy: docker compose up -d --force-recreate caddy"

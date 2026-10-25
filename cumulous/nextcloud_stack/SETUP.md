# Nextcloud setup (HTTPS only)

## 1. Start Docker Desktop
- Open **Docker** from Applications (whale icon).
- Wait until it says **Docker Desktop is running**.

## 2. Prepare ExternalSSD folders
```bash
mkdir -p /Volumes/ExternalSSD/CumulousNextcloud
mkdir -p /Volumes/ExternalSSD/CumulousPhotos
```

## 3. Launch Nextcloud (TLS front door)
```bash
cd ~/DelphiHomeController/cumulous/nextcloud_stack
export CUMULOUS_NC_DATA=/Volumes/ExternalSSD/CumulousNextcloud
docker compose up -d
# refresh LAN trusted domains after Wi‑Fi changes:
./refresh_trusted_domains.sh
```

Only **port 8443 (HTTPS)** is published. Cleartext HTTP is not exposed on the host.

## 4. Open on the Mac
- **HTTPS:** https://127.0.0.1:8443  
- Accept the self-signed certificate once (home use).
- Personal account credentials live only under `~/.cumulous/` (never git/chat).

## 5. Cumulous dual-mirror (automatic HTTPS)
Cumulous WebDAV uses `https://127.0.0.1:8443` with the stack cert pinned at  
`~/.cumulous/nextcloud_ca.pem` (TLS 1.2+, certificate verification on).

```bash
cd ~/DelphiHomeController
PYTHONPATH=. .venv/bin/python -c "from cumulous.nextcloud_client import migrate_config_to_https, tls_status; print(migrate_config_to_https()); print(tls_status())"
```

## 6. iPhone
1. App Store → **Nextcloud**  
   https://apps.apple.com/app/nextcloud/id1125420102  
2. Server: **`https://<Mac-LAN-IP>:8443`** (must be https)  
3. Trust the certificate once · log in · enable **Auto upload** for Camera.

### Cellular
Install **Tailscale** on Mac + iPhone → `https://<tailscale-ip>:8443`.

## Security posture
| Control | Status |
|---------|--------|
| Host cleartext port | **Closed** (no :8080 on host) |
| Public entry | HTTPS :8443 only (Caddy) |
| TLS version | 1.2+ |
| Certificate | **mkcert CA-signed** leaf (valid when CA trusted) |
| HSTS header | Yes (Caddy) |
| Cumulous client | HTTPS required · CA pinned · no HTTP fallback |
| Nextcloud `overwriteprotocol` | `https` |

## Make the certificate valid (trusted)

### On this Mac
Double-click:
```
~/DelphiHomeController/cumulous/nextcloud_stack/install_trusted_ca.command
```
(or run `mkcert -install` once with your Mac password).

### On iPhone
1. Safari → `http://<Mac-LAN-IP>:8765/install/nextcloud-ca`  
2. Allow → install profile  
3. **Settings → General → About → Certificate Trust Settings** → enable full trust for **Cumulous Nextcloud CA**  
4. Open Nextcloud app → `https://<Mac-LAN-IP>:8443` (should be valid / no red warning)

### Re-issue after Wi‑Fi IP change
```bash
cd ~/DelphiHomeController/cumulous/nextcloud_stack
./issue_certs.sh
docker compose up -d --force-recreate caddy
./install_trusted_ca.command   # only if CA was recreated
```

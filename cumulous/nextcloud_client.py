"""Nextcloud WebDAV client — dual-store plane with Mac HDD.

All traffic uses HTTPS. Local mkcert CA is pinned via ca_cert_path
(copied to ~/.cumulous/nextcloud_ca.pem). Plain HTTP is upgraded/rejected.
Server leaf is signed by Cumulous Local CA (mkcert) — valid when CA is trusted.
"""

from __future__ import annotations

import base64
import json
import os
import shutil
import ssl
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from cumulous.paths import ensure_internal

# Default TLS front door (Caddy) — never default to cleartext HTTP
DEFAULT_HTTPS_URL = "https://127.0.0.1:8443"
STACK_CERTS = Path(__file__).resolve().parent / "nextcloud_stack" / "certs"
# Prefer CA (mkcert root) for verification; fall back to leaf for legacy self-signed
STACK_CA = STACK_CERTS / "ca.pem"
STACK_CERT = STACK_CERTS / "cert.pem"


def nc_config_path() -> Path:
    return ensure_internal() / "nextcloud.json"


def ca_cert_path() -> Path:
    return ensure_internal() / "nextcloud_ca.pem"


def default_config() -> dict[str, Any]:
    return {
        "base_url": os.environ.get("CUMULOUS_NC_URL", DEFAULT_HTTPS_URL),
        "username": os.environ.get("CUMULOUS_NC_USER", "admin"),
        # password from env or local file only — never git
        "password": os.environ.get("CUMULOUS_NC_PASSWORD", ""),
        "remote_root": "CumulousMedia",
        "enabled": True,
        # TLS: pin stack cert; never skip verify unless explicitly set
        "require_https": True,
        "ca_cert_path": str(ca_cert_path()),
        "tls_insecure": False,  # only for emergency debugging
        "tls_min_version": "TLSv1_2",
    }


def ensure_ca_bundle() -> Path | None:
    """Install/refresh pinned CA from nextcloud_stack certs into ~/.cumulous.

    Prefers mkcert CA (ca.pem) so leaf certs verify as a proper chain.
    """
    dest = ca_cert_path()
    env_src = os.environ.get("CUMULOUS_NC_CA")
    if env_src and Path(env_src).is_file():
        src = Path(env_src)
    elif STACK_CA.is_file():
        src = STACK_CA
    elif STACK_CERT.is_file():
        src = STACK_CERT
    else:
        return dest if dest.is_file() else None
    ensure_internal()
    try:
        if (not dest.exists()) or (src.stat().st_mtime > dest.stat().st_mtime) or (
            dest.read_bytes() != src.read_bytes()
        ):
            shutil.copy2(src, dest)
            dest.chmod(0o600)
    except OSError:
        pass
    return dest if dest.is_file() else None


def normalize_https_url(url: str, *, require_https: bool = True) -> str:
    """Force HTTPS base URL; map legacy :8080 → :8443."""
    u = (url or DEFAULT_HTTPS_URL).strip().rstrip("/")
    if u.startswith("http://"):
        u = "https://" + u[len("http://") :]
        # legacy cleartext port → TLS front door
        if u.endswith(":8080"):
            u = u[: -len(":8080")] + ":8443"
        elif ":8080/" in u:
            u = u.replace(":8080/", ":8443/")
    if not u.startswith("https://"):
        if require_https:
            if "://" in u:
                raise ValueError(f"Nextcloud URL must be HTTPS: {u.split('://')[0]}://…")
            u = "https://" + u.lstrip("/")
        else:
            u = "https://" + u.lstrip("/")
    return u.rstrip("/")


def load_nc_config() -> dict[str, Any]:
    base = default_config()
    p = nc_config_path()
    if p.exists():
        try:
            base.update(json.loads(p.read_text()))
        except Exception:
            pass
    if not base.get("password"):
        # fall back to compose default only for local first-run (CEO should change)
        base["password"] = os.environ.get("CUMULOUS_NC_PASSWORD", "cumulous_nc_admin_change_me")
    # Always normalize to HTTPS when required
    require = bool(base.get("require_https", True))
    try:
        base["base_url"] = normalize_https_url(str(base.get("base_url") or DEFAULT_HTTPS_URL), require_https=require)
    except ValueError:
        base["base_url"] = DEFAULT_HTTPS_URL
    if not base.get("ca_cert_path"):
        base["ca_cert_path"] = str(ca_cert_path())
    ensure_ca_bundle()
    return base


def save_nc_config(cfg: dict[str, Any]) -> None:
    ensure_internal()
    cfg = dict(cfg)
    if cfg.get("require_https", True) and cfg.get("base_url"):
        try:
            cfg["base_url"] = normalize_https_url(str(cfg["base_url"]), require_https=True)
        except ValueError:
            cfg["base_url"] = DEFAULT_HTTPS_URL
    p = nc_config_path()
    p.write_text(json.dumps(cfg, indent=2))
    try:
        p.chmod(0o600)
    except OSError:
        pass


def migrate_config_to_https() -> dict[str, Any]:
    """Upgrade local nextcloud.json to HTTPS + pinned CA (idempotent)."""
    cfg = load_nc_config()
    cfg["require_https"] = True
    cfg["tls_insecure"] = False
    cfg["base_url"] = normalize_https_url(str(cfg.get("base_url") or DEFAULT_HTTPS_URL))
    cfg["ca_cert_path"] = str(ca_cert_path())
    ensure_ca_bundle()
    save_nc_config(cfg)
    return {
        "ok": True,
        "base_url": cfg["base_url"],
        "require_https": True,
        "ca_present": ca_cert_path().is_file(),
        # never return password/username in migrate summary
    }


def ssl_context(cfg: dict | None = None) -> ssl.SSLContext:
    """TLS 1.2+ context; verify against pinned Nextcloud cert when present."""
    cfg = cfg or load_nc_config()
    if cfg.get("tls_insecure") or os.environ.get("CUMULOUS_NC_TLS_INSECURE") == "1":
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        return ctx

    ctx = ssl.create_default_context()
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    # Prefer modern ciphers (OpenSSL defaults are fine; disallow weak if possible)
    try:
        ctx.set_ciphers("DEFAULT:@SECLEVEL=2")
    except ssl.SSLError:
        pass

    ca = cfg.get("ca_cert_path") or str(ca_cert_path())
    ensure_ca_bundle()
    if ca and Path(ca).is_file():
        ctx.load_verify_locations(cafile=ca)
        # Self-signed leaf used as trust anchor: hostname may be IP
        # check_hostname still validates SAN if cert has IP SAN
        ctx.check_hostname = True
        ctx.verify_mode = ssl.CERT_REQUIRED
    return ctx


def _urlopen(req: urllib.request.Request, *, timeout: float, cfg: dict | None = None):
    cfg = cfg or load_nc_config()
    url = req.full_url if hasattr(req, "full_url") else req.get_full_url()
    if cfg.get("require_https", True) and not str(url).startswith("https://"):
        raise urllib.error.URLError("Nextcloud client refuses non-HTTPS URL")
    ctx = ssl_context(cfg) if str(url).startswith("https://") else None
    return urllib.request.urlopen(req, timeout=timeout, context=ctx)


def _auth_header(user: str, password: str) -> str:
    token = base64.b64encode(f"{user}:{password}".encode()).decode("ascii")
    return f"Basic {token}"


def dav_base(cfg: dict | None = None) -> str:
    cfg = cfg or load_nc_config()
    base = normalize_https_url(
        str(cfg.get("base_url") or DEFAULT_HTTPS_URL),
        require_https=bool(cfg.get("require_https", True)),
    )
    user = cfg.get("username") or "admin"
    # WebDAV path — username may contain @; urllib handles encoding on request
    from urllib.parse import quote

    user_enc = quote(str(user), safe="@._-")
    return f"{base}/remote.php/dav/files/{user_enc}"


def nextcloud_reachable(cfg: dict | None = None) -> dict[str, Any]:
    cfg = cfg or load_nc_config()
    url = dav_base(cfg) + "/"
    req = urllib.request.Request(
        url,
        method="PROPFIND",
        headers={
            "Authorization": _auth_header(cfg["username"], cfg["password"]),
            "Depth": "0",
        },
    )
    try:
        with _urlopen(req, timeout=12, cfg=cfg) as resp:
            return {
                "ok": 200 <= resp.status < 400,
                "status": resp.status,
                "url": url,
                "https": url.startswith("https://"),
                "tls_verified": not bool(cfg.get("tls_insecure")),
            }
    except urllib.error.HTTPError as e:
        return {
            "ok": 200 <= e.code < 400 or e.code == 207,
            "status": e.code,
            "url": url,
            "https": True,
            "tls_verified": not bool(cfg.get("tls_insecure")),
        }
    except Exception as e:
        return {"ok": False, "error": str(e)[:200], "url": url, "https": url.startswith("https://")}


def ensure_remote_dir(remote_path: str, cfg: dict | None = None) -> bool:
    """MKCOL nested path segments under remote_root."""
    cfg = cfg or load_nc_config()
    root = (cfg.get("remote_root") or "CumulousMedia").strip("/")
    parts = [root] + [p for p in remote_path.strip("/").split("/") if p]
    built = ""
    for part in parts:
        built = f"{built}/{part}" if built else part
        url = f"{dav_base(cfg)}/{built}"
        req = urllib.request.Request(
            url,
            method="MKCOL",
            headers={"Authorization": _auth_header(cfg["username"], cfg["password"])},
        )
        try:
            with _urlopen(req, timeout=15, cfg=cfg):
                pass
        except urllib.error.HTTPError as e:
            # 405/409 often means exists
            if e.code not in (201, 405, 409, 301, 302):
                if e.code != 405:
                    continue
        except Exception:
            continue
    return True


def upload_bytes(remote_rel: str, data: bytes, cfg: dict | None = None) -> dict[str, Any]:
    cfg = cfg or load_nc_config()
    root = (cfg.get("remote_root") or "CumulousMedia").strip("/")
    rel = remote_rel.strip("/").replace("\\", "/")
    parent = "/".join(rel.split("/")[:-1])
    ensure_remote_dir(parent if parent else "", cfg)
    url = f"{dav_base(cfg)}/{root}/{rel}"
    req = urllib.request.Request(
        url,
        data=data,
        method="PUT",
        headers={
            "Authorization": _auth_header(cfg["username"], cfg["password"]),
            "Content-Type": "application/octet-stream",
            "Content-Length": str(len(data)),
        },
    )
    try:
        with _urlopen(req, timeout=120, cfg=cfg) as resp:
            return {
                "ok": resp.status in (200, 201, 204),
                "status": resp.status,
                "url": url,
                "https": True,
            }
    except urllib.error.HTTPError as e:
        return {
            "ok": e.code in (200, 201, 204),
            "status": e.code,
            "url": url,
            "error": str(e)[:120],
            "https": True,
        }
    except Exception as e:
        return {"ok": False, "error": str(e)[:200], "url": url, "https": url.startswith("https://")}


def upload_file(local: Path, remote_rel: str, cfg: dict | None = None) -> dict[str, Any]:
    data = local.read_bytes()
    return upload_bytes(remote_rel, data, cfg)


def delete_remote(remote_rel: str, cfg: dict | None = None) -> dict[str, Any]:
    """Explicit vault delete of one Nextcloud object (never automatic on re-backup)."""
    cfg = cfg or load_nc_config()
    root = (cfg.get("remote_root") or "CumulousMedia").strip("/")
    rel = remote_rel.strip("/").replace("\\", "/")
    if not rel or ".." in rel.split("/"):
        return {"ok": False, "error": "invalid_path"}
    url = f"{dav_base(cfg)}/{root}/{rel}"
    req = urllib.request.Request(
        url,
        method="DELETE",
        headers={"Authorization": _auth_header(cfg["username"], cfg["password"])},
    )
    try:
        with _urlopen(req, timeout=30, cfg=cfg) as resp:
            return {"ok": resp.status in (200, 202, 204), "status": resp.status, "url": url}
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return {"ok": True, "status": 404, "already_gone": True, "url": url}
        return {"ok": False, "status": e.code, "error": str(e)[:120], "url": url}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200], "url": url}


def remote_exists(remote_rel: str, cfg: dict | None = None) -> bool:
    cfg = cfg or load_nc_config()
    root = (cfg.get("remote_root") or "CumulousMedia").strip("/")
    url = f"{dav_base(cfg)}/{root}/{remote_rel.strip('/')}"
    req = urllib.request.Request(
        url,
        method="PROPFIND",
        headers={
            "Authorization": _auth_header(cfg["username"], cfg["password"]),
            "Depth": "0",
        },
    )
    try:
        with _urlopen(req, timeout=15, cfg=cfg) as resp:
            return 200 <= resp.status < 400 or resp.status == 207
    except urllib.error.HTTPError as e:
        return e.code in (200, 207)
    except Exception:
        return False


def tls_status() -> dict[str, Any]:
    """CEO-safe status of Nextcloud TLS posture (no secrets)."""
    cfg = load_nc_config()
    reach = nextcloud_reachable(cfg)
    return {
        "base_url": cfg.get("base_url"),
        "require_https": bool(cfg.get("require_https", True)),
        "tls_insecure": bool(cfg.get("tls_insecure")),
        "ca_cert_present": Path(cfg.get("ca_cert_path") or ca_cert_path()).is_file(),
        "reachable": bool(reach.get("ok")),
        "https": bool(reach.get("https")),
        "tls_verified": bool(reach.get("tls_verified")) and not cfg.get("tls_insecure"),
        "status": reach.get("status"),
        "error": reach.get("error"),
    }

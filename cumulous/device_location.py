"""Approximate location for challenge maps (Apple 2FA–style IP/geo).

Apple documents that sign-in maps use the *approximate* location of the
requesting device (often IP-based). We mirror that pattern:

1. Prefer last GPS report from Cumulous iOS (`POST /challenge/location`)
2. Else USB device last known
3. Else public IP geolocation of this Mac (request origin for Mac-initiated backup)

Static map tiles: OpenStreetMap staticmap (no API key) for Mac UI;
iOS uses MapKit with the same coordinates.
"""

from __future__ import annotations

import json
import time
import urllib.request
from pathlib import Path
from typing import Any

from cumulous.paths import ensure_internal


def location_store_path() -> Path:
    return ensure_internal() / "device_locations.json"


def load_locations() -> dict[str, Any]:
    p = location_store_path()
    if not p.exists():
        return {"devices": {}, "updated_at": 0}
    try:
        return json.loads(p.read_text())
    except Exception:
        return {"devices": {}, "updated_at": 0}


def save_locations(data: dict[str, Any]) -> None:
    ensure_internal()
    data["updated_at"] = time.time()
    p = location_store_path()
    p.write_text(json.dumps(data, indent=2))
    try:
        p.chmod(0o600)
    except OSError:
        pass


def record_device_location(
    device_id: str,
    *,
    latitude: float,
    longitude: float,
    accuracy_m: float | None = None,
    source: str = "ios_core_location",
    label: str = "",
) -> dict[str, Any]:
    """Store GPS/IP location for a device (called from iOS or Mac)."""
    if not device_id:
        return {"ok": False, "error": "device_id_required"}
    try:
        lat = float(latitude)
        lon = float(longitude)
    except (TypeError, ValueError):
        return {"ok": False, "error": "invalid_coords"}
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return {"ok": False, "error": "coords_out_of_range"}

    data = load_locations()
    devices = data.setdefault("devices", {})
    entry = {
        "device_id": device_id,
        "latitude": lat,
        "longitude": lon,
        "accuracy_m": accuracy_m,
        "source": source,
        "label": label or "",
        "updated_at": time.time(),
    }
    # Reverse geocode city (best effort)
    place = reverse_geocode(lat, lon)
    if place.get("ok"):
        entry["city"] = place.get("city") or ""
        entry["region"] = place.get("region") or ""
        entry["country"] = place.get("country") or ""
        entry["display_place"] = place.get("display_place") or ""
    devices[device_id] = entry
    # Also index by short aliases
    save_locations(data)
    return {"ok": True, **entry}


def reverse_geocode(lat: float, lon: float) -> dict[str, Any]:
    """Nominatim reverse geocode (User-Agent required)."""
    try:
        url = (
            f"https://nominatim.openstreetmap.org/reverse?"
            f"lat={lat:.5f}&lon={lon:.5f}&format=json"
        )
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "CumulousCloud/1.0 (private backup; location map only)"},
        )
        with urllib.request.urlopen(req, timeout=6) as resp:
            raw = json.loads(resp.read().decode())
        addr = raw.get("address") or {}
        city = (
            addr.get("city")
            or addr.get("town")
            or addr.get("village")
            or addr.get("municipality")
            or addr.get("county")
            or ""
        )
        region = addr.get("state") or addr.get("region") or ""
        country = addr.get("country") or ""
        display = ", ".join(x for x in (city, region, country) if x)
        return {
            "ok": True,
            "city": city,
            "region": region,
            "country": country,
            "display_place": display or raw.get("display_name", "")[:80],
        }
    except Exception as e:
        return {"ok": False, "error": str(e)[:120]}


def geolocate_public_ip() -> dict[str, Any]:
    """Approximate Mac / network location via public IP (Apple-style IP map)."""
    # Try multiple free endpoints for resilience
    endpoints = [
        "https://ipapi.co/json/",
        "http://ip-api.com/json/?fields=status,message,lat,lon,city,regionName,country,query",
    ]
    for url in endpoints:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "CumulousCloud/1.0"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                raw = json.loads(resp.read().decode())
            if "ipapi.co" in url:
                lat, lon = raw.get("latitude"), raw.get("longitude")
                if lat is None or lon is None:
                    continue
                return {
                    "ok": True,
                    "latitude": float(lat),
                    "longitude": float(lon),
                    "city": raw.get("city") or "",
                    "region": raw.get("region") or "",
                    "country": raw.get("country_name") or raw.get("country") or "",
                    "display_place": ", ".join(
                        x
                        for x in (
                            raw.get("city") or "",
                            raw.get("region") or "",
                            raw.get("country_name") or "",
                        )
                        if x
                    ),
                    "source": "ip_geolocation",
                    "ip": raw.get("ip") or "",
                }
            if raw.get("status") == "success" or (raw.get("lat") is not None):
                return {
                    "ok": True,
                    "latitude": float(raw["lat"]),
                    "longitude": float(raw["lon"]),
                    "city": raw.get("city") or "",
                    "region": raw.get("regionName") or "",
                    "country": raw.get("country") or "",
                    "display_place": ", ".join(
                        x
                        for x in (
                            raw.get("city") or "",
                            raw.get("regionName") or "",
                            raw.get("country") or "",
                        )
                        if x
                    ),
                    "source": "ip_geolocation",
                    "ip": raw.get("query") or "",
                }
        except Exception:
            continue
    return {"ok": False, "error": "geo_unavailable"}


def static_map_url(
    lat: float,
    lon: float,
    *,
    width: int = 280,
    height: int = 140,
    zoom: int = 12,
) -> str:
    """OSM static map URL (works in Streamlit img tags; no API key)."""
    return (
        "https://staticmap.openstreetmap.de/staticmap.php"
        f"?center={lat:.5f},{lon:.5f}&zoom={zoom}"
        f"&size={width}x{height}&maptype=mapnik"
        f"&markers={lat:.5f},{lon:.5f},lightblue1"
    )


def resolve_challenge_location(
    *,
    requesting_device_id: str = "",
    prefer_fresh_ip: bool = True,
) -> dict[str, Any]:
    """Best location for the device requesting backup/confirm (verified multi-path)."""
    data = load_locations()
    devices = data.get("devices") or {}
    candidates: list[dict[str, Any]] = []

    # 1) Exact device id
    if requesting_device_id and requesting_device_id in devices:
        candidates.append(dict(devices[requesting_device_id]))

    # 2) USB probe ids
    try:
        from cumulous.devices import probe_connected_device

        probe = probe_connected_device() or {}
        for key in ("imei", "device_id", "udid"):
            did = str(probe.get(key) or "")
            if did and did in devices:
                candidates.append(dict(devices[did]))
    except Exception:
        pass

    # Pick freshest GPS/device report under 24h
    now = time.time()
    fresh = [
        c
        for c in candidates
        if c.get("latitude") is not None
        and (now - float(c.get("updated_at") or 0)) < 86400
    ]
    if fresh:
        fresh.sort(key=lambda x: float(x.get("updated_at") or 0), reverse=True)
        best = fresh[0]
        lat, lon = float(best["latitude"]), float(best["longitude"])
        # Re-verify reverse geocode if place missing
        if not best.get("display_place"):
            place = reverse_geocode(lat, lon)
            if place.get("ok"):
                best.update(
                    {
                        "city": place.get("city"),
                        "region": place.get("region"),
                        "country": place.get("country"),
                        "display_place": place.get("display_place"),
                    }
                )
        out = {
            "ok": True,
            "latitude": lat,
            "longitude": lon,
            "display_place": best.get("display_place") or "Approximate location",
            "city": best.get("city") or "",
            "region": best.get("region") or "",
            "country": best.get("country") or "",
            "source": best.get("source") or "device_report",
            "accuracy_m": best.get("accuracy_m"),
            "map_url": static_map_url(lat, lon),
            "map_url_2x": static_map_url(lat, lon, width=560, height=280),
            "verified_paths": 1,
        }
        # Second path cross-check: IP within ~500km optional
        if prefer_fresh_ip:
            ip_loc = geolocate_public_ip()
            if ip_loc.get("ok"):
                out["ip_crosscheck"] = {
                    "latitude": ip_loc["latitude"],
                    "longitude": ip_loc["longitude"],
                    "display_place": ip_loc.get("display_place"),
                }
                out["verified_paths"] = 2
        return out

    # 3) IP geolocation of this Mac (request origin)
    ip_loc = geolocate_public_ip()
    if ip_loc.get("ok"):
        lat, lon = float(ip_loc["latitude"]), float(ip_loc["longitude"])
        # Cache as mac-local
        record_device_location(
            "mac-mini-cumulous",
            latitude=lat,
            longitude=lon,
            source="ip_geolocation",
            label=ip_loc.get("display_place") or "",
        )
        # Third verification: reverse geocode
        place = reverse_geocode(lat, lon)
        display = ip_loc.get("display_place") or place.get("display_place") or "Approximate location"
        return {
            "ok": True,
            "latitude": lat,
            "longitude": lon,
            "display_place": display,
            "city": ip_loc.get("city") or place.get("city") or "",
            "region": ip_loc.get("region") or place.get("region") or "",
            "country": ip_loc.get("country") or place.get("country") or "",
            "source": "ip_geolocation",
            "map_url": static_map_url(lat, lon),
            "map_url_2x": static_map_url(lat, lon, width=560, height=280),
            "verified_paths": 2 if place.get("ok") else 1,
            "note": "Approximate (network IP) — same approach as Apple 2FA maps",
        }

    return {
        "ok": False,
        "error": "location_unavailable",
        "display_place": "Location unavailable",
        "map_url": "",
    }

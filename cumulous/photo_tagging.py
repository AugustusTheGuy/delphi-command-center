"""Deep photo tagging for Cumulous Photos (beyond Apple Photos defaults).

Extracts and stores:
  - creation / capture date
  - GPS + reverse-geocoded place (when network allows)
  - camera / device make-model
  - scene context, setting, people, plants, objects (vision when available)
  - free-form + structured tags for search across all devices

Apple Photos.app cannot show Mac-HDD originals as iCloud placeholders; tagging
lives on the Cumulous library so every device sees the same enriched metadata.
"""

from __future__ import annotations

import base64
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from cumulous.paths import ensure_internal


def tags_db_path() -> Path:
    return ensure_internal() / "photo_tags.json"


def load_tags_db() -> dict[str, Any]:
    p = tags_db_path()
    if not p.exists():
        return {"by_digest": {}, "updated_at": 0}
    try:
        return json.loads(p.read_text())
    except Exception:
        return {"by_digest": {}, "updated_at": 0}


def save_tags_db(db: dict[str, Any]) -> None:
    ensure_internal()
    db["updated_at"] = time.time()
    p = tags_db_path()
    p.write_text(json.dumps(db, indent=2))
    try:
        p.chmod(0o600)
    except OSError:
        pass


def empty_tag_record(digest: str) -> dict[str, Any]:
    return {
        "digest": digest,
        "captured_at": None,  # unix ts if known
        "captured_at_iso": None,
        "date_source": None,  # exif | file_mtime | filename
        "location": {
            "lat": None,
            "lon": None,
            "altitude": None,
            "place_name": None,  # reverse geocode
            "city": None,
            "region": None,
            "country": None,
            "source": None,
        },
        "camera": {"make": None, "model": None, "lens": None},
        "dimensions": {"width": None, "height": None},
        "people": [],  # [{label, confidence}]
        "plants": [],
        "objects": [],  # items in frame
        "animals": [],
        "setting": None,  # indoor/outdoor/beach/...
        "context": None,  # free-text scene description
        "activities": [],
        "colors": [],  # dominant color names/hex
        "keywords": [],  # flat search tokens
        "relatable_details": [],  # any/all extra facts
        "vision": {"status": "pending", "model": None, "error": None, "raw": None},
        "enriched_at": None,
        "version": 1,
    }


def _rational_to_float(v: Any) -> float | None:
    try:
        if isinstance(v, tuple) and len(v) == 2 and v[1]:
            return float(v[0]) / float(v[1])
        return float(v)
    except Exception:
        return None


def _dms_to_decimal(dms: Any, ref: str | None) -> float | None:
    try:
        if not dms or len(dms) < 3:
            return None
        deg = _rational_to_float(dms[0]) or 0.0
        minutes = _rational_to_float(dms[1]) or 0.0
        seconds = _rational_to_float(dms[2]) or 0.0
        val = deg + minutes / 60.0 + seconds / 3600.0
        if ref in ("S", "W"):
            val = -val
        return val
    except Exception:
        return None


def extract_exif(path: Path) -> dict[str, Any]:
    """Read capture date, GPS, camera from image EXIF via Pillow."""
    out: dict[str, Any] = {
        "captured_at": None,
        "captured_at_iso": None,
        "date_source": None,
        "lat": None,
        "lon": None,
        "altitude": None,
        "make": None,
        "model": None,
        "width": None,
        "height": None,
    }
    try:
        from PIL import Image
        from PIL.ExifTags import GPSTAGS, TAGS
    except Exception:
        return out

    try:
        with Image.open(path) as im:
            out["width"], out["height"] = im.size
            raw = im._getexif() if hasattr(im, "_getexif") else None
            if not raw:
                # Pillow 10+
                raw = getattr(im, "getexif", lambda: None)()
                if raw is not None:
                    try:
                        raw = {int(k): v for k, v in raw.items()}
                    except Exception:
                        raw = None
            if not raw:
                return out
            labeled: dict[str, Any] = {}
            for tag_id, value in raw.items():
                name = TAGS.get(tag_id, str(tag_id))
                labeled[name] = value

            for key in ("DateTimeOriginal", "DateTimeDigitized", "DateTime"):
                if key in labeled and labeled[key]:
                    ts = _parse_exif_datetime(str(labeled[key]))
                    if ts:
                        out["captured_at"] = ts
                        out["captured_at_iso"] = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(ts))
                        out["date_source"] = "exif"
                        break

            out["make"] = _clean_str(labeled.get("Make"))
            out["model"] = _clean_str(labeled.get("Model"))

            gps_ifd = labeled.get("GPSInfo")
            if isinstance(gps_ifd, dict):
                gps = {}
                for k, v in gps_ifd.items():
                    gps[GPSTAGS.get(k, k)] = v
                lat = _dms_to_decimal(gps.get("GPSLatitude"), gps.get("GPSLatitudeRef"))
                lon = _dms_to_decimal(gps.get("GPSLongitude"), gps.get("GPSLongitudeRef"))
                out["lat"] = lat
                out["lon"] = lon
                alt = _rational_to_float(gps.get("GPSAltitude"))
                if alt is not None:
                    out["altitude"] = alt
    except Exception:
        pass
    return out


def _clean_str(v: Any) -> str | None:
    if v is None:
        return None
    s = str(v).strip().strip("\x00")
    return s or None


def _parse_exif_datetime(s: str) -> float | None:
    s = s.strip()
    for fmt in ("%Y:%m:%d %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y:%m:%d"):
        try:
            return time.mktime(time.strptime(s[:19] if len(s) >= 19 else s, fmt[: len(s) + fmt.count("%")]))
        except Exception:
            continue
    # looser
    m = re.match(r"(\d{4}):(\d{2}):(\d{2})[ T](\d{2}):(\d{2}):(\d{2})", s)
    if m:
        try:
            return time.mktime(
                time.struct_time(
                    (
                        int(m.group(1)),
                        int(m.group(2)),
                        int(m.group(3)),
                        int(m.group(4)),
                        int(m.group(5)),
                        int(m.group(6)),
                        0,
                        0,
                        -1,
                    )
                )
            )
        except Exception:
            return None
    return None


def dominant_colors(path: Path, k: int = 4) -> list[str]:
    """Simple palette sampling (no sklearn)."""
    try:
        from PIL import Image
    except Exception:
        return []
    try:
        with Image.open(path) as im:
            im = im.convert("RGB")
            im = im.resize((48, 48))
            # get_flattened_data preferred on newer Pillow; fallback for older
            if hasattr(im, "get_flattened_data"):
                flat = im.get_flattened_data()
                pixels = list(zip(flat[0::3], flat[1::3], flat[2::3]))
            else:
                pixels = list(im.getdata())
        # bucket
        buckets: dict[tuple[int, int, int], int] = {}
        for r, g, b in pixels:
            key = (r // 32 * 32, g // 32 * 32, b // 32 * 32)
            buckets[key] = buckets.get(key, 0) + 1
        top = sorted(buckets.items(), key=lambda x: -x[1])[:k]
        out = []
        for (r, g, b), _ in top:
            out.append(f"#{r:02x}{g:02x}{b:02x}")
            out.append(_color_name(r, g, b))
        return list(dict.fromkeys(out))
    except Exception:
        return []


def _color_name(r: int, g: int, b: int) -> str:
    if r > 200 and g > 200 and b > 200:
        return "white"
    if r < 40 and g < 40 and b < 40:
        return "black"
    if r > g and r > b:
        return "red" if r - max(g, b) > 40 else "warm"
    if g > r and g > b:
        return "green"
    if b > r and b > g:
        return "blue"
    if r > 180 and g > 140 and b < 100:
        return "gold"
    return "neutral"


def reverse_geocode(lat: float, lon: float, *, timeout: float = 4.0) -> dict[str, Any]:
    """Optional Nominatim reverse geocode (best-effort; offline-safe if fails)."""
    if os.environ.get("CUMULOUS_DISABLE_GEOCODE") == "1":
        return {}
    try:
        q = urllib.parse.urlencode({"lat": f"{lat:.6f}", "lon": f"{lon:.6f}", "format": "json"})
        req = urllib.request.Request(
            f"https://nominatim.openstreetmap.org/reverse?{q}",
            headers={"User-Agent": "CumulousCloud/1.0 (private backup; local only)"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
        addr = data.get("address") or {}
        return {
            "place_name": data.get("display_name"),
            "city": addr.get("city") or addr.get("town") or addr.get("village"),
            "region": addr.get("state") or addr.get("region"),
            "country": addr.get("country"),
            "source": "nominatim",
        }
    except Exception:
        return {}


def _ollama_vision_models() -> list[str]:
    try:
        with urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=2) as resp:
            data = json.loads(resp.read().decode())
        names = [m.get("name") or "" for m in data.get("models") or []]
        visionish = [
            n
            for n in names
            if any(x in n.lower() for x in ("llava", "vision", "moondream", "minicpm-v", "bakllava", "qwen2.5vl", "gemma3"))
        ]
        return visionish
    except Exception:
        return []


def vision_describe(path: Path) -> dict[str, Any]:
    """Call local Ollama vision model when present; structured scene tags."""
    models = _ollama_vision_models()
    if not models:
        return {"status": "skipped", "model": None, "error": "no_vision_model", "raw": None}
    model = models[0]
    try:
        raw_bytes = path.read_bytes()
        if len(raw_bytes) > 12 * 1024 * 1024:
            # downscale for vision
            from PIL import Image
            import io

            with Image.open(path) as im:
                im = im.convert("RGB")
                im.thumbnail((1280, 1280))
                buf = io.BytesIO()
                im.save(buf, format="JPEG", quality=85)
                raw_bytes = buf.getvalue()
        b64 = base64.b64encode(raw_bytes).decode("ascii")
        prompt = (
            "You are tagging a personal photo for a private backup library. "
            "Respond ONLY with compact JSON keys: "
            "people (list of strings: roles/ages if clear, no real names unless text in image), "
            "plants (list), objects (list of items), animals (list), "
            "setting (one short phrase: indoor/outdoor/beach/office/home/nature/...), "
            "context (1-2 sentence scene description), "
            "activities (list), relatable_details (list of any useful facts: weather, time of day, "
            "text visible, emotions, food, vehicles, landmarks). "
            "Be thorough and accurate. If unsure, omit rather than invent names."
        )
        body = json.dumps(
            {
                "model": model,
                "prompt": prompt,
                "images": [b64],
                "stream": False,
                "options": {"temperature": 0.2},
            }
        ).encode()
        req = urllib.request.Request(
            "http://127.0.0.1:11434/api/generate",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode())
        text = (data.get("response") or "").strip()
        parsed = _parse_json_blob(text)
        return {"status": "ok", "model": model, "error": None, "raw": text[:4000], "parsed": parsed}
    except Exception as e:
        return {"status": "error", "model": model, "error": str(e)[:200], "raw": None}


def _parse_json_blob(text: str) -> dict[str, Any]:
    if not text:
        return {}
    # strip markdown fences
    m = re.search(r"\{[\s\S]*\}", text)
    if not m:
        return {"context": text[:500]}
    try:
        return json.loads(m.group(0))
    except Exception:
        return {"context": text[:500]}


def _as_str_list(v: Any) -> list[str]:
    if v is None:
        return []
    if isinstance(v, str):
        return [v] if v.strip() else []
    if isinstance(v, list):
        out = []
        for x in v:
            if isinstance(x, dict):
                lab = x.get("label") or x.get("name") or x.get("text")
                if lab:
                    out.append(str(lab))
            else:
                s = str(x).strip()
                if s:
                    out.append(s)
        return out
    return [str(v)]


def build_keywords(rec: dict[str, Any]) -> list[str]:
    keys: list[str] = []
    loc = rec.get("location") or {}
    for k in ("place_name", "city", "region", "country"):
        if loc.get(k):
            keys.append(str(loc[k]))
    for group in ("people", "plants", "objects", "animals", "activities", "relatable_details", "colors"):
        for item in rec.get(group) or []:
            if isinstance(item, dict):
                keys.append(str(item.get("label") or item))
            else:
                keys.append(str(item))
    if rec.get("setting"):
        keys.append(str(rec["setting"]))
    if rec.get("context"):
        keys.extend(re.findall(r"[A-Za-z]{3,}", str(rec["context"]).lower())[:40])
    cam = rec.get("camera") or {}
    for k in ("make", "model"):
        if cam.get(k):
            keys.append(str(cam[k]))
    if rec.get("captured_at_iso"):
        keys.append(rec["captured_at_iso"][:10])
    # normalize unique
    seen: set[str] = set()
    out: list[str] = []
    for k in keys:
        t = k.strip().lower()
        if t and t not in seen:
            seen.add(t)
            out.append(t)
    return out[:200]


def enrich_file(
    path: Path,
    *,
    digest: str,
    filename: str = "",
    run_vision: bool = True,
    run_geocode: bool = True,
) -> dict[str, Any]:
    """Full enrichment pipeline for one media file on disk."""
    path = Path(path)
    rec = empty_tag_record(digest)
    rec["filename"] = filename or path.name

    # file mtime fallback
    try:
        mtime = path.stat().st_mtime
        rec["captured_at"] = mtime
        rec["captured_at_iso"] = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(mtime))
        rec["date_source"] = "file_mtime"
    except OSError:
        pass

    if path.suffix.lower() in {".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp", ".tif", ".tiff"}:
        exif = extract_exif(path)
        if exif.get("captured_at"):
            rec["captured_at"] = exif["captured_at"]
            rec["captured_at_iso"] = exif["captured_at_iso"]
            rec["date_source"] = exif.get("date_source") or "exif"
        rec["location"]["lat"] = exif.get("lat")
        rec["location"]["lon"] = exif.get("lon")
        rec["location"]["altitude"] = exif.get("altitude")
        if exif.get("lat") is not None:
            rec["location"]["source"] = "exif_gps"
        rec["camera"]["make"] = exif.get("make")
        rec["camera"]["model"] = exif.get("model")
        rec["dimensions"]["width"] = exif.get("width")
        rec["dimensions"]["height"] = exif.get("height")
        rec["colors"] = dominant_colors(path)

        if run_geocode and rec["location"]["lat"] is not None and rec["location"]["lon"] is not None:
            geo = reverse_geocode(float(rec["location"]["lat"]), float(rec["location"]["lon"]))
            if geo:
                rec["location"].update({k: v for k, v in geo.items() if v})

        if run_vision:
            vis = vision_describe(path)
            rec["vision"] = {
                "status": vis.get("status"),
                "model": vis.get("model"),
                "error": vis.get("error"),
                "raw": vis.get("raw"),
            }
            parsed = vis.get("parsed") or {}
            rec["people"] = [{"label": x, "confidence": None} for x in _as_str_list(parsed.get("people"))]
            rec["plants"] = [{"label": x, "confidence": None} for x in _as_str_list(parsed.get("plants"))]
            rec["objects"] = [{"label": x, "confidence": None} for x in _as_str_list(parsed.get("objects"))]
            rec["animals"] = [{"label": x, "confidence": None} for x in _as_str_list(parsed.get("animals"))]
            rec["activities"] = _as_str_list(parsed.get("activities"))
            rec["relatable_details"] = _as_str_list(parsed.get("relatable_details"))
            if parsed.get("setting"):
                rec["setting"] = str(parsed["setting"])
            if parsed.get("context"):
                rec["context"] = str(parsed["context"])
        else:
            rec["vision"]["status"] = "deferred"

    # filename hints
    name_l = (filename or path.name).lower()
    for token, label in (
        ("screenshot", "screenshot"),
        ("img_", "camera_roll"),
        ("portrait", "portrait"),
        ("pano", "panorama"),
    ):
        if token in name_l:
            rec["relatable_details"].append(label)

    rec["keywords"] = build_keywords(rec)
    rec["enriched_at"] = time.time()
    return rec


def upsert_tags(digest: str, record: dict[str, Any]) -> dict[str, Any]:
    db = load_tags_db()
    by = db.setdefault("by_digest", {})
    by[digest] = record
    save_tags_db(db)
    return record


def get_tags(digest: str) -> dict[str, Any] | None:
    return (load_tags_db().get("by_digest") or {}).get(digest)


def search_by_query(query: str, *, limit: int = 200) -> list[str]:
    """Return digests matching keyword/query across tags."""
    q = (query or "").strip().lower()
    if not q:
        return []
    tokens = [t for t in re.split(r"\s+", q) if t]
    hits: list[tuple[int, str]] = []
    for digest, rec in (load_tags_db().get("by_digest") or {}).items():
        blob_parts = list(rec.get("keywords") or [])
        blob_parts.append(str(rec.get("context") or ""))
        blob_parts.append(str(rec.get("setting") or ""))
        blob_parts.append(str((rec.get("location") or {}).get("place_name") or ""))
        blob = " ".join(blob_parts).lower()
        score = sum(1 for t in tokens if t in blob)
        if score:
            hits.append((score, digest))
    hits.sort(key=lambda x: (-x[0], x[1]))
    return [d for _, d in hits[:limit]]


def enrich_and_store(
    path: Path,
    *,
    digest: str,
    filename: str = "",
    run_vision: bool | None = None,
) -> dict[str, Any]:
    if run_vision is None:
        run_vision = os.environ.get("CUMULOUS_PHOTO_VISION", "1") != "0"
    # vision can be slow — default on only when a vision model exists
    if run_vision and not _ollama_vision_models():
        run_vision = False
    rec = enrich_file(path, digest=digest, filename=filename, run_vision=run_vision)
    return upsert_tags(digest, rec)

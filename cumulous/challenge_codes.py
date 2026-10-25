"""Time-sensitive 4-digit codes with multi-device fan-out.

Hard rules:
  - At most ONE unconsumed active code per (purpose, apple_account) at a time.
  - Re-spawn within the same backup/confirm request returns the existing code
    (no second push window / no dialog spam).
  - Fan-out: all Apple Account devices ∪ CEO override ∪ USB-attached phone ∪ Mac.
"""

from __future__ import annotations

import json
import secrets
import time
from dataclasses import asdict, dataclass, field

from cumulous.paths import challenges_file, ensure_internal

TTL_SEC = 30 * 60  # 30 minutes
# Debounce re-push of the same active challenge
REPUSH_MIN_INTERVAL_SEC = 90


@dataclass
class Challenge:
    code: str
    purpose: str
    created_at: float
    expires_at: float
    requesting_user_id: str
    fanout_device_ids: list[str] = field(default_factory=list)
    consumed: bool = False
    id: str = ""
    last_pushed_at: float = 0.0

    def __post_init__(self) -> None:
        if not self.id:
            self.id = secrets.token_hex(8)
        if not self.last_pushed_at:
            self.last_pushed_at = self.created_at


def _load() -> list[dict]:
    ensure_internal()
    cf = challenges_file()
    if not cf.exists():
        return []
    try:
        return json.loads(cf.read_text())
    except Exception:
        return []


def _save(items: list[dict]) -> None:
    ensure_internal()
    cf = challenges_file()
    cf.write_text(json.dumps(items, indent=2))
    try:
        cf.chmod(0o600)
    except OSError:
        pass


def generate_code() -> str:
    return f"{secrets.randbelow(10000):04d}"


def fanout_targets(
    requesting_user_id: str,
    user_device_ids: list[str],
    ceo_override_device_ids: list[str],
) -> list[str]:
    """Union of requesting user's devices and all CEOOVERRIDE devices."""
    seen: set[str] = set()
    out: list[str] = []
    for d in list(user_device_ids) + list(ceo_override_device_ids):
        if d and d not in seen:
            seen.add(d)
            out.append(d)
    return out


def _find_active(
    items: list[dict],
    *,
    purpose: str,
    requesting_user_id: str,
    now: float,
) -> dict | None:
    for item in items:
        if item.get("consumed"):
            continue
        if item.get("purpose") != purpose:
            continue
        if str(item.get("requesting_user_id") or "") != str(requesting_user_id):
            continue
        if float(item.get("expires_at") or 0) <= now:
            continue
        return item
    return None


def _payload_from_item(item: dict, push_results: list | None = None) -> dict:
    targets = list(item.get("fanout_device_ids") or [])
    labels = []
    try:
        from cumulous.challenge_push import _device_label

        labels = [_device_label(t) for t in targets]
    except Exception:
        labels = list(targets)
    return {
        "challenge_id": item.get("id"),
        "code": item.get("code"),
        "expires_at": item.get("expires_at"),
        "ttl_sec": max(0, int(float(item.get("expires_at") or 0) - time.time())),
        "fanout_device_ids": targets,
        "fanout_device_labels": labels,
        "push_results": push_results or [],
        "reused": True,
        "display_message": (
            f"Enter this 4-digit code (valid 30 minutes): {item.get('code')}. "
            "Pushed once to your Apple devices and this Mac."
        ),
    }


def spawn_challenge_for_user(
    *,
    purpose: str,
    requesting_user_id: str,
    now: float | None = None,
    force_new: bool = False,
) -> dict:
    from cumulous.devices import ceo_override_device_ids, devices_for_apple_account, devices_for_user

    user_ids = devices_for_user(requesting_user_id)
    for did in devices_for_apple_account(requesting_user_id):
        if did not in user_ids:
            user_ids.append(did)
    return spawn_challenge(
        purpose=purpose,
        requesting_user_id=requesting_user_id,
        user_device_ids=user_ids,
        ceo_override_device_ids=ceo_override_device_ids(),
        now=now,
        force_new=force_new,
    )


def spawn_challenge_for_apple_account(
    *,
    purpose: str,
    apple_account_id: str,
    include_mac_mini: bool = True,
    now: float | None = None,
    force_new: bool = False,
) -> dict:
    """4-digit code → all devices of this Apple Account ∪ CEO Override ∪ USB phone."""
    from cumulous.apple_accounts import devices_for_apple_account as acct_devices
    from cumulous.devices import ceo_override_device_ids, devices_for_apple_account

    user_ids = list(acct_devices(apple_account_id))
    for did in devices_for_apple_account(apple_account_id):
        if did not in user_ids:
            user_ids.append(did)
    ceo_ids = ceo_override_device_ids()
    if not include_mac_mini:
        ceo_ids = [d for d in ceo_ids if d not in ("mac-mini-cumulous", "mac-mini-local")]
        user_ids = [d for d in user_ids if d not in ("mac-mini-cumulous", "mac-mini-local")]

    return spawn_challenge(
        purpose=purpose,
        requesting_user_id=apple_account_id,
        user_device_ids=user_ids,
        ceo_override_device_ids=ceo_ids,
        now=now,
        force_new=force_new,
    )


def spawn_challenge(
    *,
    purpose: str,
    requesting_user_id: str,
    user_device_ids: list[str],
    ceo_override_device_ids: list[str],
    now: float | None = None,
    force_new: bool = False,
) -> dict:
    """Create OR reuse a single active 4-digit code for this purpose+account.

    Hard-cap: never spawn a second unconsumed code for the same purpose while
    the first is still valid (unless force_new=True after user explicitly
    requests a new code).
    """
    now = now if now is not None else time.time()
    items = _load()
    # Prune expired
    items = [i for i in items if float(i.get("expires_at", 0)) > now - 3600]

    existing = None if force_new else _find_active(
        items, purpose=purpose, requesting_user_id=requesting_user_id, now=now
    )

    requesting_device_id = ""
    try:
        from cumulous.devices import probe_connected_device

        probe = probe_connected_device() or {}
        requesting_device_id = str(
            probe.get("imei") or probe.get("device_id") or probe.get("udid") or ""
        )
    except Exception:
        pass

    targets = fanout_targets(requesting_user_id, user_device_ids, ceo_override_device_ids)

    if existing:
        # Hard-cap hit: return same code. Re-push only if enough time passed
        # (e.g. phone was offline) — still ONE logical code, not a second window type.
        last_push = float(existing.get("last_pushed_at") or existing.get("created_at") or 0)
        push_results: list = []
        if (now - last_push) >= REPUSH_MIN_INTERVAL_SEC:
            push_results = push_code_to_devices(
                str(existing["code"]),
                targets,
                purpose=purpose,
                challenge_id=str(existing.get("id") or ""),
                expires_at=float(existing.get("expires_at") or 0),
                requesting_user_id=requesting_user_id,
                requesting_device_id=requesting_device_id,
                replace_all_pending=True,
            )
            for i, it in enumerate(items):
                if it.get("id") == existing.get("id"):
                    items[i]["last_pushed_at"] = now
                    items[i]["fanout_device_ids"] = targets
                    break
            _save(items)
        payload = _payload_from_item(existing, push_results)
        payload["reused"] = True
        payload["hard_cap"] = True
        return payload

    # Invalidate any other unconsumed codes for this purpose (cleanup orphans)
    for i, it in enumerate(items):
        if (
            not it.get("consumed")
            and it.get("purpose") == purpose
            and float(it.get("expires_at") or 0) > now
        ):
            items[i]["consumed"] = True
            items[i]["superseded"] = True

    code = generate_code()
    ch = Challenge(
        code=code,
        purpose=purpose,
        created_at=now,
        expires_at=now + TTL_SEC,
        requesting_user_id=requesting_user_id,
        fanout_device_ids=targets,
        last_pushed_at=now,
    )
    items.append(asdict(ch))
    _save(items)

    push_results = push_code_to_devices(
        code,
        targets,
        purpose=purpose,
        challenge_id=ch.id,
        expires_at=ch.expires_at,
        requesting_user_id=requesting_user_id,
        requesting_device_id=requesting_device_id,
        replace_all_pending=True,
    )
    labels = []
    try:
        from cumulous.challenge_push import _device_label

        labels = [_device_label(t) for t in targets]
    except Exception:
        labels = list(targets)

    return {
        "challenge_id": ch.id,
        "code": code,
        "expires_at": ch.expires_at,
        "ttl_sec": TTL_SEC,
        "fanout_device_ids": targets,
        "fanout_device_labels": labels,
        "push_results": push_results,
        "reused": False,
        "hard_cap": True,
        "display_message": (
            f"Enter this 4-digit code (valid 30 minutes): {code}. "
            "Pushed once to your Apple devices and this Mac."
        ),
    }


def verify_challenge(code: str, *, purpose: str | None = None, now: float | None = None) -> bool:
    now = now if now is not None else time.time()
    digits = "".join(c for c in str(code) if c.isdigit())
    items = _load()
    for i, item in enumerate(items):
        if item.get("consumed"):
            continue
        if purpose and item.get("purpose") != purpose:
            continue
        if float(item.get("expires_at", 0)) < now:
            continue
        if str(item.get("code")) == digits:
            items[i]["consumed"] = True
            _save(items)
            try:
                from cumulous.challenge_push import mark_consumed

                mark_consumed(challenge_id=str(item.get("id") or ""), code=digits)
            except Exception:
                pass
            return True
    return False


def push_code_to_devices(
    code: str,
    device_ids: list[str],
    *,
    purpose: str,
    challenge_id: str = "",
    expires_at: float = 0,
    requesting_user_id: str = "",
    requesting_device_id: str = "",
    replace_all_pending: bool = True,
) -> list[dict]:
    from cumulous.challenge_push import push_code_live

    return push_code_live(
        code,
        device_ids,
        purpose=purpose,
        challenge_id=challenge_id,
        expires_at=expires_at,
        requesting_user_id=requesting_user_id,
        requesting_device_id=requesting_device_id,
        replace_all_pending=replace_all_pending,
    )

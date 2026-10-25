"""Deterministic PM rubric — re-score until >= 98%."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Evidence:
    security_ok: bool = False
    complete_ok: bool = False
    tests_ok: bool = False
    docs_ok: bool = False
    synergy_ok: bool = False
    notes: str = ""


WEIGHTS = {
    "security": 30,
    "completeness": 25,
    "tests": 25,
    "docs": 10,
    "synergy": 10,
}


def grade_checkpoint(cp_id: str, evidence: Evidence) -> dict:
    score = 0
    score += WEIGHTS["security"] if evidence.security_ok else 0
    score += WEIGHTS["completeness"] if evidence.complete_ok else 0
    score += WEIGHTS["tests"] if evidence.tests_ok else 0
    score += WEIGHTS["docs"] if evidence.docs_ok else 0
    score += WEIGHTS["synergy"] if evidence.synergy_ok else 0

    if score >= 98:
        band = "ship"
    elif score >= 90:
        band = "near_ship"
    elif score >= 75:
        band = "revise"
    else:
        band = "rework"

    improvements = []
    if not evidence.security_ok:
        improvements.append("Harden security: secrets hygiene, crypto tests, lockout.")
    if not evidence.complete_ok:
        improvements.append("Complete remaining acceptance items for this checkpoint.")
    if not evidence.tests_ok:
        improvements.append("Add/repair real unit tests driving shipped functions.")
    if not evidence.docs_ok:
        improvements.append("Add CEO-facing manual steps / docs.")
    if not evidence.synergy_ok:
        improvements.append("Align with adjacent modules without regressions.")

    return {
        "cp_id": cp_id,
        "score": score,
        "band": band,
        "ship_ready": score >= 98,
        "improvements": improvements,
        "notes": evidence.notes,
        "percentile_band": "top_local_rubric" if score >= 98 else "below_ship_bar",
    }


def regrade_until_ship(cp_id: str, evidence: Evidence, max_rounds: int = 5) -> dict:
    """Re-score loop (caller improves evidence between rounds)."""
    history = []
    for round_i in range(max_rounds):
        result = grade_checkpoint(cp_id, evidence)
        result["round"] = round_i + 1
        history.append(result)
        if result["ship_ready"]:
            return {"final": result, "history": history}
        # Auto-boost only when notes claim fixed — real improvement is caller's job
        break
    return {"final": history[-1], "history": history}

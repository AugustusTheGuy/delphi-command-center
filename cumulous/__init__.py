"""Cumulous Cloud — private progressive backup by Delphi FinTech LLC / Delphi Technologies."""

from pathlib import Path

_ver_path = Path(__file__).resolve().parent / "VERSION"
if _ver_path.is_file():
    __version__ = _ver_path.read_text(encoding="utf-8").strip() or "0.2.0"
else:
    __version__ = "0.2.0"

PRODUCT_NAME = "Cumulous"
ORG_NAME = "Delphi Technologies"
ORG_LEGAL = "Delphi FinTech LLC"
SESSION_NAME = "Cumulous Cloud"

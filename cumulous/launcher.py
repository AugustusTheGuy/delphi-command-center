"""Mac launcher: Delphi Technologies splash → Streamlit / Cumulous.app.

Always syncs Desktop/Dock icon to latest assets before launch.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

from cumulous.app_update import on_app_launch, package_version, projected_splash_duration_sec
from cumulous.splash import ICON_PATH, ORG_TITLE, PRODUCT_SUB

ASSETS = Path(__file__).resolve().parent / "assets"
ICON_MAC = ASSETS / "icons" / "Cumulous.icns"
ICON_PNG = ASSETS / "icons" / "cumulous_mac_icon.png"


def find_primary_app() -> Path | None:
    candidates = [
        Path.home() / "Desktop" / "Cumulous.app",
        Path.home() / "Applications" / "Cumulous.app",
        Path("/Applications/Cumulous.app"),
        Path(__file__).resolve().parents[1] / "dist" / "Cumulous.app",
        Path(__file__).resolve().parents[1] / "Cumulous.app",
    ]
    for c in candidates:
        if c.is_dir():
            return c
    return None


def ensure_streamlit(port: int = 8502) -> str:
    url = f"http://127.0.0.1:{port}"
    try:
        import urllib.request

        with urllib.request.urlopen(url, timeout=1) as r:
            if r.status == 200:
                return url
    except Exception:
        pass

    root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root)
    venv_streamlit = root / ".venv" / "bin" / "streamlit"
    cmd = [
        str(venv_streamlit if venv_streamlit.exists() else "streamlit"),
        "run",
        str(root / "cumulous" / "app.py"),
        "--server.port",
        str(port),
        "--server.headless",
        "true",
        "--browser.gatherUsageStats",
        "false",
    ]
    subprocess.Popen(
        cmd,
        cwd=str(root),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    for _ in range(48):
        time.sleep(0.25)
        try:
            import urllib.request

            with urllib.request.urlopen(url, timeout=1) as r:
                if r.status == 200:
                    return url
        except Exception:
            continue
    return url


def show_delphi_splash_macos(duration: float | None = None) -> None:
    """Medium borderless centered Delphi Technologies splash (AppleScript + HTML)."""
    duration = duration if duration is not None else projected_splash_duration_sec()
    icon = ICON_PNG if ICON_PNG.exists() else ICON_PATH
    # Size scales with projected load: medium box ~320–420 pt
    box = int(min(420, max(300, 260 + duration * 45)))
    half = box // 2

    # Write a tiny HTML splash and open via osascript Safari/WebKit is heavy;
    # Use System Events floating process with pure AppleScript window if possible.
    # Practical path: Python + tkinter borderless if available, else brief notification.
    try:
        import tkinter as tk
        from PIL import Image, ImageTk

        root = tk.Tk()
        root.overrideredirect(True)
        root.configure(bg="#000000")
        root.attributes("-topmost", True)
        sw = root.winfo_screenwidth()
        sh = root.winfo_screenheight()
        x = (sw - box) // 2
        y = (sh - box) // 2
        root.geometry(f"{box}x{box}+{x}+{y}")

        frame = tk.Frame(root, bg="#000000", highlightthickness=0, bd=0)
        frame.pack(expand=True, fill="both")

        if icon.is_file():
            im = Image.open(icon).convert("RGBA")
            side = int(box * 0.42)
            im = im.resize((side, side), Image.Resampling.LANCZOS)
            photo = ImageTk.PhotoImage(im)
            lbl = tk.Label(frame, image=photo, bg="#000000", bd=0, highlightthickness=0)
            lbl.image = photo  # type: ignore
            lbl.pack(pady=(int(box * 0.14), 12))
        tk.Label(
            frame,
            text=ORG_TITLE,
            fg="#f5f5f7",
            bg="#000000",
            font=("SF Pro Display", 18, "bold"),
        ).pack()
        tk.Label(
            frame,
            text=PRODUCT_SUB,
            fg="#8e8e93",
            bg="#000000",
            font=("SF Pro Text", 13),
        ).pack(pady=(4, 0))
        tk.Label(
            frame,
            text=f"v{package_version()}",
            fg="#636366",
            bg="#000000",
            font=("SF Pro Text", 10),
        ).pack(pady=(6, 0))

        root.update()
        root.after(int(duration * 1000), root.destroy)
        root.mainloop()
        return
    except Exception:
        pass

    # Fallback notification
    try:
        subprocess.run(
            [
                "osascript",
                "-e",
                f'display notification "Starting {PRODUCT_SUB}…" with title "{ORG_TITLE}" sound name "Glass"',
            ],
            check=False,
            timeout=5,
        )
    except Exception:
        pass
    time.sleep(min(duration, 1.8))


def launch(*, prefer_primary: bool = False, streamlit_port: int = 8502) -> dict:
    # Always refresh Desktop/Dock icons + version before UI
    meta = on_app_launch()
    dur = float((meta.get("splash") or {}).get("duration_sec") or projected_splash_duration_sec())
    show_delphi_splash_macos(dur)

    # Prefer Streamlit Cumulous Cloud (always latest code); primary .app is just a launcher
    url = ensure_streamlit(streamlit_port)
    webbrowser.open(url)
    return {
        "mode": "streamlit",
        "url": url,
        "version": package_version(),
        "splash_duration": dur,
        "launch_sync": meta.get("launch_sync"),
    }


def main(argv: list[str] | None = None) -> int:
    res = launch()
    print(res)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

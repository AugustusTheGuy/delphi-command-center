# Delphi Command Center

A unified, self-hosted home and dev command center for an Apple Silicon Mac, built with Streamlit. One local dashboard brings together local AI (Ollama/MLX routing), Home Assistant and HomeKit control, Nextcloud-style storage ("Cumulous"), a TV remote, agent orchestration, system and Wi-Fi monitoring, project management and a privacy-suite bridge.

## Highlights

- **Multi-model AI router**: `core/multi_router.py` and `core/ollama_router.py` choose a local model for each task, and `prompt_optimizer.py` rewrites prompts before dispatch.
- **Agent orchestration**: agent discovery and registry, with a live agent monitor and orchestrator tabs.
- **Home automation**: a Home Assistant REST client plus TV-remote and home-management tabs.
- **Front page and Settings**: a simple home screen with big shortcuts, a live setup checklist (drive, Jellyfin, Sonarr) and a "What went wrong" view of the server log with API keys, tokens and passwords redacted (`core/log_view.py`). The last page you opened is remembered (`core/ui_state.py`).
- **Local session and profiles**: the dashboard is a single-user local app with per-user profiles; there is no password, so it is meant to listen only on `127.0.0.1` (the macOS shell enforces this). No credentials are stored in the repo; a random session secret is generated into `data/.auth_secret` (mode 600) on first run.
- **Media servers**: Jellyfin and Sonarr addresses and keys are entered on the Settings page and saved to `data/media_services.json` (mode 600), or read from `JELLYFIN_URL`/`JELLYFIN_API_KEY`/`SONARR_URL`/`SONARR_API_KEY`. Library builds are cached briefly (`core/ttl_cache.py`), and a missing or read-only external drive never takes the app down.
- **Cumulous**: a self-hosted media and photo library service with its own tests.
- **Scoped tooling**: a sandboxed terminal runner for OS management tasks.
- **Per-profile theming**: three user-chosen colors flow into CSS variables, with strict `#RRGGBB` validation so profile data cannot inject CSS.
- **Typeahead search**: a custom Streamlit component (`components/typeahead_bar.py`) with ordered-subsequence ranking in `core/typeahead.py`, merging local files, Jellyfin and Sonarr into one video index (`core/media_index.py`).
- **Native macOS shell**: `macos/main.swift` (Cocoa + WebKit) launches the Streamlit server on `127.0.0.1:8501`, adopts or restarts it if it dies, and hosts it in a floating panel that follows you across Spaces and full-screen apps; build with `macos/build_app.sh` (set `DHC_ROOT` if the checkout is not at `~/delphi-command-center`).
- **Doc redaction helper**: `scripts/redact_docs.py` scrubs quoted credentials from Markdown/text without printing them.
- An iOS companion target lives in `ios/`, and a Docker Compose setup is included.

## Architecture

```
Streamlit app (delphi_command_center.py)
 ├─ tabs/        one module per dashboard tab (UI)
 ├─ core/        services: auth, state, routers, HA client, monitors
 ├─ components/  shared UI (branded splash, widgets)
 ├─ cumulous/    media/library service
 └─ data/        local runtime state (gitignored)
```

## Project tree

```
delphi-command-center/
├── .streamlit/
│   └── … 1 files
├── components/
│   ├── typeahead_frontend/
│   └── … 3 files
├── core/
│   └── … 27 Python modules
├── cumulous/
│   ├── assets/
│   │   └── app/
│   ├── nextcloud_stack/
│   │   └── … 4 files
│   └── … media/photo library service
├── hooks/
│   └── … 1 files
├── macos/
│   └── main.swift, build_app.sh
├── ios/
│   ├── Cumulous/
│   │   ├── Services/
│   │   ├── Theme/
│   │   ├── Views/
│   │   └── … 1 files
│   └── … 1 files
├── scripts/
│   └── … 10 files
├── tabs/
│   └── … 16 Python modules
├── tests/
│   ├── dhc/
│   └── … 27 test modules
├── README.md
├── delphi_command_center.py
├── docker-compose.yml
├── requirements.txt
├── setup.sh
└── setup_py2app.py
```

## Setup

```bash
./setup.sh
source .venv/bin/activate
streamlit run delphi_command_center.py --server.address 127.0.0.1 --server.port 8501
pytest -q tests        # full suite passes on Linux, Python 3.13
```

There is no login screen, so keep it on `127.0.0.1`. For remote access, use Tailscale with ACLs and put your own auth in front of it. Don't expose port 8501 to your LAN or the public internet.

## Tech stack

Python · Streamlit · pandas · Plotly · psutil · bcrypt · cryptography · Ollama/MLX · Home Assistant API · Docker Compose · Swift (iOS companion)

## License

MIT, see [LICENSE](LICENSE).

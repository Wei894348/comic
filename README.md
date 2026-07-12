# comic18

`comic18` is a Python desktop downloader with a PyQt5 main app and an optional
Ameath desktop pet companion. The main downloader manages search, album details,
chapter selection, download queues, local cache, PDF generation, and reader
state. The desktop pet provides tray controls, quick interactions, AI chat, and
optional CosyVoice speech synthesis.

## Project Layout

```text
downloader.py              # main entry; also launches the desktop pet subprocess
jm_app/                    # PyQt downloader application
  backend/                 # runtime paths, cache, services, and persistence
  frontend/                # Qt UI, splash screen, dialogs, reader views
desktop_pet/               # Ameath desktop pet
  config/                  # safe default config files
  assets/                  # bundled pet UI/media assets
  src/                     # pet runtime, AI chat, tray, media, and UI modules
assets/                    # downloader assets such as icons
JM下载器.spec              # PyInstaller build configuration
requirements.txt           # runtime dependencies
```

Runtime data is intentionally kept out of Git. Downloaded comics, cache files,
sessions, local databases, logs, and build outputs are ignored by `.gitignore`.

## Setup

```powershell
cd F:\project\comic18
python -m pip install -r requirements.txt
```

For the existing packaged build environment, use:

```powershell
.\.venv_build\Scripts\python.exe -m pip install -r requirements.txt
```

## Run From Source

```powershell
python .\downloader.py
```

The downloader starts the desktop pet automatically. The pet can also be shown
from the downloader tray/menu actions.

## AI And Voice Configuration

The committed default file is intentionally empty:

```text
desktop_pet/config/cosyvoice.yaml
```

For local CosyVoice credentials, create this ignored file:

```text
desktop_pet/config/cosyvoice.local.yaml
```

Example:

```yaml
cosyvoice:
  enabled: true
  api_key: "your-dashscope-api-key"
  voice_id: "your-cosyvoice-voice-id"
  model: "cosyvoice-v3.5-plus"
```

Environment variables are also supported:

```text
DASHSCOPE_API_KEY
COSYVOICE_VOICE_ID
COSYVOICE_MODEL
```

## Build

```powershell
cd F:\project\comic18
.\.venv_build\Scripts\pyinstaller.exe --noconfirm .\JM下载器.spec
```

The packaged application is written to:

```text
F:\project\comic18\dist\JM下载器
```

To deploy it manually, copy the contents of that folder to:

```text
F:\project\JM下载器
```

Close any running `JM下载器.exe` process before overwriting the deployed folder.

## Git Hygiene

Commit source, documentation, default configuration, and build configuration.
Do not commit downloaded comic resources, reader cache, session data, local
SQLite databases, logs, `dist/`, or `build/`.

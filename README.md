# SETTING UP FOR DEVELOPMENT
## Install venv tools
sudo apt-get update && sudo apt-get install -y python3-bpfcc bpfcc-tools libbpfcc-dev linux-headers-$(uname -r)

sudo apt-get update
sudo apt-get install -y python3.12-venv

## Create venv using Python 3.12 
python3.12 -m venv venv (Ubuntu)
py -3.12 -m venv venv (Windows)

## Activate venv
source venv/bin/activate (Ubuntu)
venv\Scripts\activate   (this is for windows)

## Upgrade pip
pip install --upgrade pip
pip install setuptools

## Install your requirements
pip install -r requirements.txt

## Capture tuning
`machine-vision` reads optional capture settings from `.env`:

- `CAPTURE_WIDTH` default: `1920`
- `CAPTURE_HEIGHT` default: `1080`

Capture FPS now comes from `fps` in the relevant `VisCfg` returned by `getVisCfg()` in `src/machine_cfg.py`. Default: `30`.

If two cameras work but the third camera opens and then fails on the first frame read, reduce capture load first. Example:

```bash
CAPTURE_WIDTH=1280
CAPTURE_HEIGHT=720
```

Then lower `fps` for that machine in `src/machine_cfg.py` if needed. The current camera driver may keep reporting `30 FPS` even when a lower FPS is requested, so lowering resolution is usually the most effective first change.

If you only want one active camera at a time, set `disconnectOthersOnConnectRequest=True` in the relevant machine config returned from `getVisCfg()` in `src/machine_cfg.py`. When enabled, a connect request will disconnect any other active cameras before opening the requested camera.

If your runtime does not maintain a continuous heartbeat and you would rather drop active camera connections than move the device into `ABORTING`, set `DISCONNECT_CAMERAS_ON_HEARTBEAT_TIMEOUT=true`.

## Recordings path in Docker
Use `RECORDINGS_DIR` in `.env` to set the recordings path. `machine-vision`
uses the same path on the host and inside the container.

Examples:
- typical setup: `RECORDINGS_DIR=/opt/recordings`
- this IPC: `RECORDINGS_DIR=/recordings_drive`


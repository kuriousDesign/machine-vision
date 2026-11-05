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

## Stream-only Docker service
The stream-only compose file runs the camera workers without the PLC-driven
recording service. By default, it continuously streams the Screener (camera 0)
and reconnects when the camera is unplugged or its capture fails. MQTT/UI group
switching is disabled for this deployment; camera status is still published.
The requested capture rate defaults to 30 FPS and can be overridden with
`STREAM_ONLY_REQUESTED_FPS` in `.env`. Actual FPS may be lower depending on the
camera and USB bandwidth. The camera capture remains at 1280x720, while MJPEG
streams are downscaled to a maximum of 640x360 to reduce browser decode and
network load when viewing multiple cameras.

On the other IPC, set these values in that IPC's `.env` before starting the
same compose file to stream the other three cameras simultaneously:

```env
STREAM_ONLY_CAMERA_IDS=1,2,3
STREAM_ONLY_GROUP_CONTROL_ENABLED=false
```

Camera IDs are defined in `src/machine_cfg.py`: 1 is Extruder, 2 is Beakers,
and 3 is Mixing Bowl. Start the service on either IPC with:

```bash
docker compose -f docker-compose.stream-only.yml up -d
```

Set `STREAM_ONLY_GROUP_CONTROL_ENABLED=true` if MQTT/UI group switching is
needed again. The standard `docker-compose.yml` service and UI command
functionality are unchanged.

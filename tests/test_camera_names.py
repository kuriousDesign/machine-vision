import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cameras import camera_names


def test_parse_v4l2_devices_output_keeps_identical_models_distinct():
    output = """USB Camera: USB Camera (usb-0000:00:14.0-3-4.4):
\t/dev/video0
\t/dev/video1

USB Camera: USB Camera (usb-0000:00:14.0-3-9.2):
\t/dev/video2
\t/dev/video3
"""

    cameras = camera_names._parse_v4l2_devices_output(output)

    assert cameras == [
        {"index": 0, "name": "USB Camera: USB Camera"},
        {"index": 2, "name": "USB Camera: USB Camera"},
    ]


def test_get_unique_camera_names_and_indices_returns_cache_copy(monkeypatch):
    output = """USB Camera: USB Camera (usb-0000:00:14.0-3-4.4):
\t/dev/video0
\t/dev/video1
"""

    class CompletedProcess:
        def __init__(self, stdout):
            self.stdout = stdout

    monkeypatch.setattr(camera_names, "_CAMERA_LIST_CACHE", [])
    monkeypatch.setattr(camera_names, "_CAMERA_LIST_CACHE_TIME", 0.0)
    monkeypatch.setattr(camera_names, "get_camera_serial", lambda index: f"serial-{index}")
    monkeypatch.setattr(camera_names, "get_camera_usb_port", lambda index: f"port-{index}")
    monkeypatch.setattr(
        camera_names.subprocess,
        "run",
        lambda *args, **kwargs: CompletedProcess(output),
    )

    first = camera_names.get_unique_camera_names_and_indices()
    first[0]["serial"] = "mutated"
    second = camera_names.get_unique_camera_names_and_indices()

    assert second == [
        {
            "index": 0,
            "name": "USB Camera: USB Camera",
            "serial": "serial-0",
            "usb_port": "port-0",
        }
    ]
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType
from types import SimpleNamespace
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


if "aiohttp" not in sys.modules:
    aiohttp_module = ModuleType("aiohttp")

    class DummyApplication:
        def __init__(self):
            self.router = SimpleNamespace(add_get=lambda *args, **kwargs: None)

    aiohttp_module.web = SimpleNamespace(
        Application=DummyApplication,
        AppRunner=object,
        TCPSite=object,
        StreamResponse=object,
    )
    aiohttp_module.client_exceptions = SimpleNamespace(ClientConnectionError=Exception)
    sys.modules["aiohttp"] = aiohttp_module

if "cv2" not in sys.modules:
    cv2_module = ModuleType("cv2")
    cv2_module.CAP_PROP_FRAME_WIDTH = 3
    cv2_module.CAP_PROP_FRAME_HEIGHT = 4
    cv2_module.CAP_PROP_FPS = 5
    cv2_module.VideoWriter_fourcc = lambda *args: 0
    cv2_module.VideoWriter = object
    cv2_module.VideoCapture = object
    sys.modules["cv2"] = cv2_module

from cameras.camera_device import CameraDevice


class FakeCapture:
    def get(self, prop):
        values = {
            3: 1920,
            4: 1080,
            5: 30.0,
        }
        return values.get(prop, 0)


class FakeWriter:
    def __init__(self, filename, fourcc, fps, frame_size):
        self.filename = filename
        self.opened = True
        self._frames = []

    def isOpened(self):
        return self.opened

    def write(self, frame):
        self._frames.append(frame)

    def release(self):
        os.makedirs(os.path.dirname(self.filename), exist_ok=True)
        with open(self.filename, "wb") as handle:
            handle.write(b"frame-data" * max(1, len(self._frames)))


class FakeFailedPopen:
    def __init__(self, command, stdin=None, stdout=None, stderr=None, text=None):
        self.command = command
        self.returncode = 1
        if stderr is not None:
            stderr.write("simulated ffmpeg failure\n")
            stderr.flush()

    def wait(self, timeout=None):
        return self.returncode

    def kill(self):
        return None


class RecordWorkerShutdownTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.camera = CameraDevice(0, "Test", 1234, 8000)
        self.camera.cap = FakeCapture()
        self.camera.temp_filename = os.path.join(self.temp_dir.name, "live_recording_cam0.mp4")
        self.camera.save_filename = os.path.join(self.temp_dir.name, "saved_recording_cam0.mp4")

    def _start_worker(self):
        started = self.camera.start_record_worker()
        self.assertTrue(started)
        self.camera.rec_queue.put_nowait(object())

    @patch("cameras.camera_device.cv2.VideoWriter", side_effect=FakeWriter)
    def test_stop_recording_stops_worker(self, _video_writer):
        self._start_worker()

        self.camera.save_requested = False
        worker_stopped = self.camera.stop_record_worker(join_timeout=1.0)

        self.assertTrue(worker_stopped)
        self.assertTrue(self.camera.is_record_worker_done())
        self.assertFalse(self.camera.is_record_worker_active())
        self.assertFalse(self.camera._rec_worker_last_join_timed_out)
        self.assertFalse(self.camera._rec_running.is_set())

    @patch("cameras.camera_device.subprocess.Popen", side_effect=FakeFailedPopen)
    @patch("cameras.camera_device.cv2.VideoWriter", side_effect=FakeWriter)
    def test_failed_save_keeps_temp_file(self, _video_writer, _mock_popen):
        self._start_worker()

        self.camera.save_requested = True
        worker_stopped = self.camera.stop_record_worker(join_timeout=1.0)

        self.assertTrue(worker_stopped)
        self.assertTrue(self.camera.is_record_worker_done())
        self.assertFalse(self.camera.is_record_worker_active())
        self.assertFalse(self.camera._rec_worker_save_success)
        self.assertIn("simulated ffmpeg failure", self.camera._rec_worker_last_error)
        self.assertTrue(os.path.exists(self.camera.temp_filename))


if __name__ == "__main__":
    unittest.main()
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import stream_only_service
from machine_cfg import ConnectionSearchType
from stream_only_service import StreamOnlyService


def _connected_service():
    service = object.__new__(StreamOnlyService)
    service.cfg = SimpleNamespace(
        poll_period_ms=1000,
        connection_search_type=ConnectionSearchType.USB_PORT,
        camera_hw_port="3-4.4",
        camera_serial="",
    )
    service.cap = object()
    service.camera = SimpleNamespace(camera_index=0)
    service._next_camera_scan_at = 0.0
    return service


def test_connected_camera_reuses_index_until_next_scan(monkeypatch):
    service = _connected_service()
    service._next_camera_scan_at = 100.0
    monkeypatch.setattr(stream_only_service.time, "monotonic", lambda: 99.9)

    def fail_scan():
        raise AssertionError("unexpected camera scan")

    monkeypatch.setattr(service, "_resolve_camera_index", fail_scan)

    assert service._resolve_camera_index_if_due() == 0


def test_connected_camera_rescans_after_poll_interval(monkeypatch):
    service = _connected_service()
    service._next_camera_scan_at = 100.0
    monkeypatch.setattr(stream_only_service.time, "monotonic", lambda: 100.0)
    resolved_ids = []
    monkeypatch.setattr(service, "_resolve_camera_index", lambda: resolved_ids.append(1) or 1)

    assert service._resolve_camera_index_if_due() == 1
    assert resolved_ids == [1]
    assert service._next_camera_scan_at == 101.0


def test_stream_sends_only_new_camera_frames():
    assert stream_only_service._is_new_frame(101, 100)
    assert stream_only_service._is_new_frame(100, None)
    assert not stream_only_service._is_new_frame(100, 100)
    assert not stream_only_service._is_new_frame(None, 100)


def test_stream_frame_is_downscaled_without_upscaling():
    full_size_frame = np.zeros((720, 1280, 3), dtype=np.uint8)
    downscaled = stream_only_service._resize_stream_frame(full_size_frame)

    assert downscaled.shape == (360, 640, 3)

    smaller_frame = np.zeros((180, 320, 3), dtype=np.uint8)
    assert stream_only_service._resize_stream_frame(smaller_frame) is smaller_frame

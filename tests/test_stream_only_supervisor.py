import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from service_stream_only_supervisor import _build_always_on_group


def _vis_cfg(camera_ids):
    return SimpleNamespace(
        cameraCfgs=[SimpleNamespace(id=camera_id) for camera_id in camera_ids]
    )


def test_always_on_group_contains_all_selected_cameras_in_order():
    group = _build_always_on_group(_vis_cfg([0, 1, 2, 3]), [1, 2, 3])

    assert group == {"always": {"label": "Always-on", "camera_ids": [1, 2, 3]}}


def test_always_on_group_defaults_to_all_configured_cameras():
    group = _build_always_on_group(_vis_cfg([0, 1]), None)

    assert group["always"]["camera_ids"] == [0, 1]


def test_always_on_group_rejects_unknown_camera_ids():
    with pytest.raises(ValueError, match="Unknown camera IDs"):
        _build_always_on_group(_vis_cfg([0, 1]), [2])


def test_always_on_group_rejects_duplicate_camera_ids():
    with pytest.raises(ValueError, match="duplicate camera IDs"):
        _build_always_on_group(_vis_cfg([0, 1]), [1, 1])


def test_always_on_group_rejects_empty_camera_selection():
    with pytest.raises(ValueError, match="at least one camera"):
        _build_always_on_group(_vis_cfg([0, 1]), [])

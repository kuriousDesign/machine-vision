import json
import os
import signal
import subprocess
import sys
import threading
import time

from config import build_vis_cfg, normalize_machine_topic_id, MACHINE_ID
from machine_cfg import ConnectionSearchType
import paho.mqtt.client as mqtt


STREAM_GROUPS = {
    "mixer": {"label": "Mixer", "camera_ids": [2, 3]},
    "screener": {"label": "Screener", "camera_ids": [0]},
    "extruder": {"label": "Extruder", "camera_ids": [1]},
}


class StreamGroupController:
    def __init__(self, machine_id: str, available_groups: dict[str, dict], requested_fps: int):
        normalized_machine_id = normalize_machine_topic_id(machine_id)
        self.available_groups = available_groups
        self.requested_fps = requested_fps
        self.control_topic = f"vision_{normalized_machine_id}/vision_stream/group_req"
        self.status_topic = f"vision_{normalized_machine_id}/vision_stream/group_status"
        self.client = mqtt.Client()
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message
        self.mqtt_is_connected = False
        self._lock = threading.Lock()
        self._requested_group_key = self._resolve_default_group_key()
        self._active_group_key: str | None = None
        self._is_switching = False

        mqtt_username = os.getenv("MQTT_USERNAME", "")
        mqtt_password = os.getenv("MQTT_PASSWORD", "")
        if mqtt_username:
            self.client.username_pw_set(mqtt_username, mqtt_password)

    def _resolve_default_group_key(self) -> str:
        raw_default_group_key = os.getenv("STREAM_ONLY_DEFAULT_GROUP", "mixer").strip().lower()
        if raw_default_group_key in self.available_groups:
            return raw_default_group_key

        return next(iter(self.available_groups))

    def _build_status_payload(self) -> dict:
        with self._lock:
            active_group_key = self._active_group_key
            requested_group_key = self._requested_group_key
            is_switching = self._is_switching

        displayed_group_key = active_group_key or requested_group_key
        displayed_group = self.available_groups[displayed_group_key]

        return {
            "activeGroup": active_group_key,
            "requestedGroup": requested_group_key,
            "switching": is_switching,
            "cameraIds": displayed_group["camera_ids"],
            "requestedFps": self.requested_fps,
            "availableGroups": [
                {
                    "key": group_key,
                    "label": group["label"],
                    "cameraIds": group["camera_ids"],
                }
                for group_key, group in self.available_groups.items()
            ],
        }

    def _publish_status(self) -> None:
        if not self.mqtt_is_connected:
            return

        message_dict = {
            "timestamp": int(time.time() * 1000),
            "payload": self._build_status_payload(),
        }
        self.client.publish(self.status_topic, json.dumps(message_dict), qos=0, retain=True)

    def _on_connect(self, client, userdata, flags, rc):
        print(f"[STREAM_ONLY_SUPERVISOR] Connected to MQTT broker for group control (rc={rc})")
        self.mqtt_is_connected = True
        client.subscribe(self.control_topic, qos=0)
        self._publish_status()

    def _on_disconnect(self, client, userdata, rc):
        print(f"[STREAM_ONLY_SUPERVISOR] Disconnected from MQTT broker for group control (rc={rc})")
        self.mqtt_is_connected = False

    def _on_message(self, client, userdata, message):
        try:
            envelope = json.loads(message.payload.decode("utf-8"))
        except Exception as exc:
            print(f"[STREAM_ONLY_SUPERVISOR] Failed to parse group request: {exc}")
            return

        payload = envelope.get("payload") if isinstance(envelope, dict) else None
        if not isinstance(payload, dict):
            print("[STREAM_ONLY_SUPERVISOR] Ignoring group request without payload object")
            return

        requested_group_key = str(payload.get("group") or payload.get("groupKey") or "").strip().lower()
        if requested_group_key not in self.available_groups:
            print(f"[STREAM_ONLY_SUPERVISOR] Ignoring unknown group request: {requested_group_key}")
            return

        with self._lock:
            self._requested_group_key = requested_group_key
            self._is_switching = self._active_group_key != requested_group_key

        print(f"[STREAM_ONLY_SUPERVISOR] Received group switch request: {requested_group_key}")
        self._publish_status()

    def start(self) -> None:
        broker_ip = os.getenv("MQTT_BROKER_IP", "localhost")
        broker_port = int(os.getenv("MQTT_PORT", "1883"))
        print(f"[STREAM_ONLY_SUPERVISOR] Connecting to MQTT broker {broker_ip}:{broker_port} for group control")
        self.client.connect(broker_ip, broker_port, keepalive=10)
        self.client.loop_start()

    def stop(self) -> None:
        if self.mqtt_is_connected:
            self._publish_status()
        self.client.loop_stop()
        self.client.disconnect()

    def get_requested_group_key(self) -> str:
        with self._lock:
            return self._requested_group_key

    def mark_group_active(self, active_group_key: str) -> None:
        with self._lock:
            self._active_group_key = active_group_key
            self._is_switching = False
        self._publish_status()

    def mark_group_stopped(self) -> None:
        with self._lock:
            self._active_group_key = None
            self._is_switching = True
        self._publish_status()


def _parse_selected_camera_ids(raw_camera_ids: str | None) -> list[int] | None:
    if raw_camera_ids is None:
        return None

    stripped_value = raw_camera_ids.strip()
    if not stripped_value:
        return None

    return [int(camera_id.strip()) for camera_id in stripped_value.split(",") if camera_id.strip()]


def _build_camera_env(base_env: dict[str, str], cam_cfg, requested_fps: int, machine_id: str) -> dict[str, str]:
    camera_env = base_env.copy()
    normalized_machine_id = normalize_machine_topic_id(machine_id)
    connection_search_type = getattr(cam_cfg, "connectionSearchType", None)

    if not connection_search_type:
        connection_search_type = ConnectionSearchType.USB_PORT if cam_cfg.hwPort else ConnectionSearchType.SERIAL_NUMBER

    camera_env.update(
        {
            "STREAM_ONLY_CAMERA_ID": str(cam_cfg.id),
            "STREAM_ONLY_CAMERA_NAME": cam_cfg.name,
            "STREAM_ONLY_CAMERA_SERIAL": cam_cfg.serialNumber,
            "STREAM_ONLY_CAMERA_USB_PORT": cam_cfg.hwPort,
            "STREAM_ONLY_STREAM_PORT": str(cam_cfg.streamingPort),
            "STREAM_ONLY_CONNECTION_SEARCH_TYPE": connection_search_type.value,
            "STREAM_ONLY_REQUESTED_FPS": str(requested_fps),
            "STREAM_ONLY_AUTO_STREAM": "true",
            "STREAM_ONLY_STATUS_PUBLISH_ENABLED": "true",
            "STREAM_ONLY_STATUS_TOPIC": f"vision_{normalized_machine_id}/vision_stream/{cam_cfg.id}/status",
        }
    )

    return camera_env


def _resolve_requested_fps(default_fps: int) -> int:
    raw_requested_fps = os.getenv("STREAM_ONLY_REQUESTED_FPS")
    if raw_requested_fps is None or not raw_requested_fps.strip():
        return default_fps

    return int(raw_requested_fps)


def _build_available_groups(vis_cfg, selected_camera_ids: list[int] | None) -> dict[str, dict]:
    camera_cfg_by_id = {cam_cfg.id: cam_cfg for cam_cfg in vis_cfg.cameraCfgs}
    allowed_camera_ids = set(selected_camera_ids) if selected_camera_ids is not None else set(camera_cfg_by_id)
    available_groups: dict[str, dict] = {}

    for group_key, group in STREAM_GROUPS.items():
        filtered_camera_ids = [camera_id for camera_id in group["camera_ids"] if camera_id in allowed_camera_ids]
        if not filtered_camera_ids:
            continue

        available_groups[group_key] = {
            "label": group["label"],
            "camera_ids": filtered_camera_ids,
        }

    return available_groups


def _terminate_processes(processes: list[subprocess.Popen]) -> None:
    for process in processes:
        if process.poll() is None:
            process.terminate()

    deadline = time.time() + 5
    for process in processes:
        if process.poll() is not None:
            continue
        remaining_seconds = deadline - time.time()
        if remaining_seconds <= 0:
            break
        try:
            process.wait(timeout=remaining_seconds)
        except subprocess.TimeoutExpired:
            pass

    for process in processes:
        if process.poll() is None:
            process.kill()


def main() -> int:
    vis_cfg = build_vis_cfg()
    selected_camera_ids = _parse_selected_camera_ids(os.getenv("STREAM_ONLY_CAMERA_IDS"))
    camera_cfg_by_id = {cam_cfg.id: cam_cfg for cam_cfg in vis_cfg.cameraCfgs}
    available_groups = _build_available_groups(vis_cfg, selected_camera_ids)

    if not available_groups:
        print("[STREAM_ONLY_SUPERVISOR] No camera groups available for current selection; exiting")
        return 1

    requested_fps = _resolve_requested_fps(vis_cfg.fps)
    base_env = os.environ.copy()
    processes: list[subprocess.Popen] = []
    active_group_key: str | None = None
    group_controller = StreamGroupController(MACHINE_ID, available_groups, requested_fps)

    def start_group(group_key: str) -> list[subprocess.Popen]:
        next_processes: list[subprocess.Popen] = []
        group = available_groups[group_key]
        print(
            f"[STREAM_ONLY_SUPERVISOR] Activating group {group_key} "
            f"with cameras {group['camera_ids']}"
        )
        for camera_id in group["camera_ids"]:
            cam_cfg = camera_cfg_by_id[camera_id]
            camera_env = _build_camera_env(base_env, cam_cfg, requested_fps, MACHINE_ID)
            command = [sys.executable, "src/service_stream_only.py"]
            print(
                f"[STREAM_ONLY_SUPERVISOR] Starting camera {cam_cfg.id} ({cam_cfg.name}) "
                f"on port {cam_cfg.streamingPort} with searchType={camera_env['STREAM_ONLY_CONNECTION_SEARCH_TYPE']}"
            )
            next_processes.append(subprocess.Popen(command, env=camera_env))
        return next_processes

    def handle_signal(signum, _frame):
        print(f"[STREAM_ONLY_SUPERVISOR] Received signal {signum}; stopping camera workers")
        _terminate_processes(processes)
        group_controller.stop()
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    group_controller.start()

    try:
        while True:
            requested_group_key = group_controller.get_requested_group_key()
            if requested_group_key != active_group_key:
                if processes:
                    print(
                        f"[STREAM_ONLY_SUPERVISOR] Switching from {active_group_key} to {requested_group_key}; "
                        "stopping current camera workers"
                    )
                    _terminate_processes(processes)
                    processes = []

                processes = start_group(requested_group_key)
                active_group_key = requested_group_key
                group_controller.mark_group_active(active_group_key)

            exited_processes = [process for process in processes if process.poll() is not None]
            if exited_processes:
                for process in exited_processes:
                    print(
                        f"[STREAM_ONLY_SUPERVISOR] Camera worker exited with code {process.returncode}; "
                        f"restarting group {active_group_key}"
                    )
                _terminate_processes(processes)
                processes = []
                active_group_key = None
                group_controller.mark_group_stopped()
                time.sleep(1)
                continue
            time.sleep(1)
    finally:
        _terminate_processes(processes)
        group_controller.stop()


if __name__ == "__main__":
    raise SystemExit(main())
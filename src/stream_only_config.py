from dataclasses import dataclass
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from machine_cfg import ConnectionSearchType


ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

load_dotenv(ROOT_DIR / ".env")


def _read_bool_env(name: str, default: bool = False) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    return raw_value.strip().lower() in {"1", "true", "yes", "on"}


def _read_int_env(name: str, default: int) -> int:
    raw_value = os.getenv(name)
    if raw_value is None or not raw_value.strip():
        return default
    return int(raw_value)


def normalize_machine_topic_id(machine_id: str) -> str:
    trimmed_machine_id = machine_id.strip()
    if not trimmed_machine_id:
        raise ValueError("MACHINE_ID is required to build MQTT topic namespaces")

    trailing_digits = ""
    for character in reversed(trimmed_machine_id):
        if character.isdigit():
            trailing_digits = character + trailing_digits
            continue
        break

    if trailing_digits:
        return trailing_digits

    sanitized_machine_id = "".join(
        character if character.isalnum() or character in {"_", "-"} else "_"
        for character in trimmed_machine_id
    ).strip("_")

    if not sanitized_machine_id:
        raise ValueError(f"Unable to normalize MACHINE_ID for MQTT topics: {machine_id}")

    return sanitized_machine_id


@dataclass(frozen=True)
class StreamOnlyConfig:
    mqtt_broker_ip: str
    mqtt_port: int
    mqtt_username: str
    mqtt_password: str
    machine_id: str
    camera_id: int
    camera_name: str
    camera_serial: str
    camera_hw_port: str
    stream_port: int
    requested_fps: int
    connection_search_type: ConnectionSearchType
    auto_stream: bool
    status_publish_enabled: bool
    status_publish_topic: str
    status_publish_interval_ms: int
    poll_period_ms: int
    reconnect_delay_ms: int


def build_stream_only_config() -> StreamOnlyConfig:
    machine_id = os.getenv("MACHINE_ID", "UNKNOWN_MACHINE")
    camera_id = _read_int_env("STREAM_ONLY_CAMERA_ID", 0)
    camera_name = os.getenv("STREAM_ONLY_CAMERA_NAME", f"Camera {camera_id}").strip() or f"Camera {camera_id}"
    camera_serial = os.getenv("STREAM_ONLY_CAMERA_SERIAL", "").strip()
    camera_hw_port = os.getenv("STREAM_ONLY_CAMERA_USB_PORT", "").strip()
    raw_connection_search_type = os.getenv(
        "STREAM_ONLY_CONNECTION_SEARCH_TYPE",
        ConnectionSearchType.USB_PORT.value,
    ).strip()
    connection_search_type = ConnectionSearchType(raw_connection_search_type)

    if connection_search_type == ConnectionSearchType.USB_PORT and not camera_hw_port:
        raise ValueError("STREAM_ONLY_CAMERA_USB_PORT is required when using USB_PORT search")

    if connection_search_type == ConnectionSearchType.SERIAL_NUMBER and not camera_serial:
        raise ValueError("STREAM_ONLY_CAMERA_SERIAL is required when using SERIAL_NUMBER search")

    normalized_machine_id = normalize_machine_topic_id(machine_id)
    default_status_topic = f"vision_{normalized_machine_id}/vision_stream/{camera_id}/status"

    return StreamOnlyConfig(
        mqtt_broker_ip=os.getenv("MQTT_BROKER_IP", "localhost"),
        mqtt_port=_read_int_env("MQTT_PORT", 1883),
        mqtt_username=os.getenv("MQTT_USERNAME", ""),
        mqtt_password=os.getenv("MQTT_PASSWORD", ""),
        machine_id=machine_id,
        camera_id=camera_id,
        camera_name=camera_name,
        camera_serial=camera_serial,
        camera_hw_port=camera_hw_port,
        stream_port=_read_int_env("STREAM_ONLY_STREAM_PORT", 8000 + camera_id),
        requested_fps=_read_int_env("STREAM_ONLY_REQUESTED_FPS", 30),
        connection_search_type=connection_search_type,
        auto_stream=_read_bool_env("STREAM_ONLY_AUTO_STREAM", True),
        status_publish_enabled=_read_bool_env("STREAM_ONLY_STATUS_PUBLISH_ENABLED", True),
        status_publish_topic=os.getenv("STREAM_ONLY_STATUS_TOPIC", default_status_topic),
        status_publish_interval_ms=_read_int_env("STREAM_ONLY_STATUS_PUBLISH_INTERVAL_MS", 1000),
        poll_period_ms=_read_int_env("STREAM_ONLY_POLL_PERIOD_MS", 1000),
        reconnect_delay_ms=_read_int_env("STREAM_ONLY_RECONNECT_DELAY_MS", 1000),
    )
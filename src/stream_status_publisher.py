import json
import time
from typing import Any

import paho.mqtt.client as mqtt

from stream_only_config import StreamOnlyConfig


class StreamStatusPublisher:
    def __init__(self, cfg: StreamOnlyConfig, camera: Any):
        self.cfg = cfg
        self.camera = camera
        self.client = mqtt.Client()
        self.mqtt_is_connected = False
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect

        if self.cfg.mqtt_username:
            self.client.username_pw_set(self.cfg.mqtt_username, self.cfg.mqtt_password)

    def _on_connect(self, client, userdata, flags, rc):
        print(f"[STREAM_STATUS] Connected to MQTT broker {self.cfg.mqtt_broker_ip}:{self.cfg.mqtt_port}")
        self.mqtt_is_connected = True

    def _on_disconnect(self, client, userdata, rc):
        print(f"[STREAM_STATUS] Disconnected from MQTT broker (rc={rc})")
        self.mqtt_is_connected = False

    def start(self):
        if not self.cfg.status_publish_enabled:
            print("[STREAM_STATUS] MQTT status publishing disabled")
            return

        print(f"[STREAM_STATUS] Connecting to MQTT broker {self.cfg.mqtt_broker_ip}:{self.cfg.mqtt_port}")
        self.client.connect(self.cfg.mqtt_broker_ip, self.cfg.mqtt_port, keepalive=10)
        self.client.loop_start()

    def stop(self):
        if not self.cfg.status_publish_enabled:
            return

        self.client.loop_stop()
        self.client.disconnect()

    async def run(self):
        if not self.cfg.status_publish_enabled:
            return

        while True:
            if self.mqtt_is_connected:
                self.publish_status()
            await __import__("asyncio").sleep(self.cfg.status_publish_interval_ms / 1000)

    def publish_status(self):
        latest_frame_timestamp_ms = getattr(
            self.camera,
            "latest_frame_timestamp_ms",
            getattr(self.camera, "latest_segment_timestamp_ms", None),
        )
        status_payload = {
            "cameraId": self.camera.id,
            "cameraName": self.camera.camera_name,
            "hwPort": self.camera.hw_port,
            "latestFrameTimestampMs": latest_frame_timestamp_ms,
            "latestSegmentTimestampMs": getattr(self.camera, "latest_segment_timestamp_ms", None),
            "streamPort": self.camera.stream_port,
            "streamPath": getattr(self.camera, "stream_path", "/stream"),
            "streamProtocol": getattr(self.camera, "stream_protocol", "mjpeg"),
            "isPluggedIn": self.camera.state.isPluggedIn,
            "isConnected": self.camera.state.isConnected,
            "isStreaming": self.camera.state.isStreaming,
            "recordingState": int(self.camera.state.recordingState),
            "videoDeviceNodeString": self.camera.state.videoDeviceNodeString,
            "captureFpsEstimate": getattr(self.camera, "_capture_fps_estimate", None),
        }
        message_dict = {
            "timestamp": int(time.time() * 1000),
            "payload": status_payload,
        }
        self.client.publish(self.cfg.status_publish_topic, json.dumps(message_dict), qos=0)
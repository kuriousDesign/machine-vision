import json
import time

import paho.mqtt.client as mqtt

class CameraController:
    def __init__(self, broker="localhost", port=1883):
        self.client = mqtt.Client()
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.broker = broker
        self.port = port

    def _on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            print("Connected successfully")
            self.client.publish("cameras/1/cmd", json.dumps({"cmd": "connect"}))
            time.sleep(3)
            self.client.publish("cameras/1/cmd", json.dumps({"cmd": "start_stream"}))
        else:
            print(f"Connection failed with code {rc}")

    def _on_disconnect(self, client, userdata, rc):
        print("Disconnected")

    def connect(self):
        self.client.connect(self.broker, self.port, 60)
        self.client.loop_start()

    def disconnect(self):
        self.client.loop_stop()
        self.client.disconnect()


if __name__ == "__main__":
    controller = CameraController()
    controller.connect()
    time.sleep(2)
    controller.disconnect()
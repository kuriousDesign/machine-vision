import asyncio
from .camera_device_old import CameraDevice

class CameraManager:
    def __init__(self, camera_count: int):
        self.cameras = [CameraDevice(i) for i in range(camera_count)]

    async def start(self):
        tasks = [cam.poll_for_device() for cam in self.cameras]
        await asyncio.gather(*tasks)

    def get_idle_camera(self):
        for cam in self.cameras:
            if cam.state == "IDLE":
                return cam
        return None

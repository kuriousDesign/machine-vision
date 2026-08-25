import asyncio
from config import MQTT_BROKER_IP, MQTT_PORT, build_vis_cfg, cameraIdToString
from machine_cfg import ConnectionSearchType
from camera_service import CameraService
from cameras.camera_device import CameraDevice, CAPTURE_HEIGHT, CAPTURE_WIDTH

async def main():
    # Create camera devices
    # for each camera in CAMERA_MAP, create a CameraDevice
    cameras = {}
    vis_cfg = build_vis_cfg()
    print(f"[SERVICE] Requested capture settings: {CAPTURE_WIDTH}x{CAPTURE_HEIGHT} @ {vis_cfg.fps} FPS")
    for cam_cfg in vis_cfg.cameraCfgs:
        cam_id = cam_cfg.id
        camera_serial = cam_cfg.serialNumber
        camera_name = cam_cfg.name or cameraIdToString(cam_id)
        stream_port = cam_cfg.streamingPort
        if vis_cfg.connectionSearchType == ConnectionSearchType.USB_PORT:
            print(f"[SERVICE] Configuring camera {cam_id}: name={camera_name}, hwPort={cam_cfg.hwPort}, searchType={vis_cfg.connectionSearchType.value}")
        else:
            print(f"[SERVICE] Configuring camera {cam_id}: name={camera_name}, serial={camera_serial}, hwPort={cam_cfg.hwPort}, searchType={vis_cfg.connectionSearchType.value}")
        cameras[cam_id] = CameraDevice(cam_id, camera_name, camera_serial, stream_port=stream_port, auto_connect=vis_cfg.autoConnect, auto_start_stream=vis_cfg.autoStream, hw_port=cam_cfg.hwPort, connection_search_type=vis_cfg.connectionSearchType, requested_fps=vis_cfg.fps)
    print(f"[SERVICE] Created cameras: {list(cameras.keys())}")
    # Create service
    camera_service = CameraService(
        mqtt_host=MQTT_BROKER_IP,
        mqtt_port=MQTT_PORT,
        cameras= cameras,
    )

    # Run service
    await camera_service.run()

asyncio.run(main())

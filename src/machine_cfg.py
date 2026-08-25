from dataclasses import dataclass, field
from enum import Enum


class ConnectionSearchType(str, Enum):
    SERIAL_NUMBER = "SERIAL_NUMBER"  # match camera by ID_SERIAL_SHORT (udevadm)
    USB_PORT = "USB_PORT"  # match camera by physical USB bus/port path (e.g. "1-3")


@dataclass
class CameraCfg:
    serialNumber: str = ""
    name: str = ""
    id: int = 0
    streamingPort: int = 0
    hwPort: str = ""  # physical USB bus/port string, e.g. "1-3" (used when connectionSearchType is USB_PORT)



@dataclass
class VisCfg:
    deviceId: int = 0  # used with the PLC's DeviceIds
    numCameras: int = 0
    visionDeviceTopicPath: str = ""
    cameraCfgs: list[CameraCfg] = field(default_factory=list)
    connectionSearchType: ConnectionSearchType = ConnectionSearchType.SERIAL_NUMBER
    fps: int = 30
    autoConnect: bool = False
    autoStream: bool = True
    disconnectOthersOnConnectRequest: bool = False

class MachineIds(str, Enum):
    TUBELINER_00251 = "TUBELINER_00251"
    JAKES_THINKPAD = "JAKES_THINKPAD"
    SAW_00225 = "SAW_00225"
    TLX_00254 = "TLX_00254"

def getVisCfg(machine_id: MachineIds) -> VisCfg:
    match machine_id:
        case MachineIds.TUBELINER_00251:
            return VisCfg(
                deviceId=5,
                visionDeviceTopicPath= "machine/1/4/7/5",
                numCameras=2,
                cameraCfgs=[
                    CameraCfg(serialNumber="200901010001", name="Short", id=0, streamingPort=8000),
                    CameraCfg(serialNumber="200901010001", name="Tall", id=1, streamingPort=8001)
                ]
            )   
        case MachineIds.JAKES_THINKPAD:
            return VisCfg(
                deviceId=13,
                visionDeviceTopicPath= "machine/1/4/10/13",
                numCameras=2,
                cameraCfgs=[
                    CameraCfg(serialNumber="N/A", name="Webcam", id=0, streamingPort=8000),
                    CameraCfg(serialNumber="N/A", name="Webcam", id=1, streamingPort=8001)
                ]
            )
        case MachineIds.SAW_00225:
            return VisCfg(
                deviceId=13,
                visionDeviceTopicPath= "machine/1/13",
                numCameras=1,
                cameraCfgs=[
                    CameraCfg(serialNumber="88817FAF", name="Benchtop", id=0, streamingPort=8000)
                ]
            )
        case MachineIds.TLX_00254:
            return VisCfg(
                deviceId=5,
                visionDeviceTopicPath= "machine/1/5",
                numCameras=4,
                connectionSearchType=ConnectionSearchType.USB_PORT,
                fps=30,
                disconnectOthersOnConnectRequest=True,
                cameraCfgs=[
                    CameraCfg(name="Screener", id=0, streamingPort=8000, hwPort="3-4.4"),
                    CameraCfg(name="Extruder", id=1, streamingPort=8001, hwPort="3-9.2"),
                    CameraCfg(name="Beakers", id=2, streamingPort=8002, hwPort="3-9.3"),
                    CameraCfg(name="Mixing Bowl", id=3, streamingPort=8003, hwPort="3-9.4"),
                ]
            )
        case _:
            raise ValueError(f"Unknown machine_id {machine_id}")
            raise ValueError(f"Unknown machine_id {machine_id}")

        



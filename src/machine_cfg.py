from dataclasses import dataclass
from enum import Enum


@dataclass
class MachineCameraCfg:
    serialNumber: str = ""
    name: str = ""
    id: int = 0

@dataclass
class MachineCfg:
    machineName: str
    deviceId: int #used with the PLC's DeviceIds
    numCameras: int
    visionDeviceTopicPath: str
    cameraCfgs: list[MachineCameraCfg]

class MachineIds(str, Enum):
    TUBELINER_00251 = "TUBELINER_00251"
    JAKES_THINKPAD = "JAKES_THINKPAD"
    SAW_00225 = "SAW_00225"
    TLX_00254 = "TLX_00254"

def getMachineCfg(machine_id: MachineIds) -> MachineCfg:
    match machine_id:
        case MachineIds.TUBELINER_00251:
            return MachineCfg(
                machineName=MachineIds.TUBELINER_00251.value,
                deviceId=5,
                visionDeviceTopicPath= "machine/1/4/7/5",
                numCameras=2,
                cameraCfgs=[
                    MachineCameraCfg(serialNumber="200901010001", name="Short", id=0),
                    MachineCameraCfg(serialNumber="200901010001", name="Tall", id=1)
                ]
            )   
        case MachineIds.JAKES_THINKPAD:
            return MachineCfg(
                machineName=MachineIds.JAKES_THINKPAD.value,
                deviceId=13,
                visionDeviceTopicPath= "machine/1/4/10/13",
                numCameras=2,
                cameraCfgs=[
                    MachineCameraCfg(serialNumber="N/A", name="Webcam", id=0),
                    MachineCameraCfg(serialNumber="N/A", name="Webcam", id=1)
                ]
            )
        case MachineIds.SAW_00225:
            return MachineCfg(
                machineName=MachineIds.SAW_00225.value,
                deviceId=13,
                #visionStsTopic= "machine/1/4/10/13/sts",
                visionDeviceTopicPath= "machine/1/13",
                numCameras=1,
                cameraCfgs=[
                    MachineCameraCfg(serialNumber="88817FAF", name="Benchtop", id=0)
                ]
            )
        case MachineIds.TLX_00254:
            return MachineCfg(
                machineName=MachineIds.TLX_00254.value,
                deviceId=5,
                visionDeviceTopicPath= "machine/1/4/5",
                numCameras=2,
                cameraCfgs=[
                    MachineCameraCfg(serialNumber="C9A45D6F", name="Screener", id=0),
                    MachineCameraCfg(serialNumber="200901010002", name="Mixer", id=1)
                ]
            )
        case _:
            raise ValueError(f"Unknown machine_id {machine_id}")
        

     
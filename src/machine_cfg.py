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
    cameraCfgs: list[MachineCameraCfg]

class MachineIds(str, Enum):
    TUBELINER_002551 = "TUBELINER_002551"
    JAKES_THINKPAD = "JAKES_THINKPAD"

def getMachineCfg(machine_id: MachineIds) -> MachineCfg:
    match machine_id:
        case MachineIds.TUBELINER_002551:
            return MachineCfg(
                machineName=MachineIds.TUBELINER_002551.value,
                deviceId=13,
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
                numCameras=2,
                cameraCfgs=[
                    MachineCameraCfg(serialNumber="N/A", name="Webcam", id=0),
                    MachineCameraCfg(serialNumber="N/A", name="Webcam", id=1)
                ]
            )
        case _:
            raise ValueError(f"Unknown machine_id {machine_id}")
        

     
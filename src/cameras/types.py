from enum import Enum, IntEnum
from dataclasses import dataclass, field

class CameraRecordingState(IntEnum):
    STOPPED = 0
    RECORDING = 1
    SAVING = 2

# create camera status structure which has isConnected, RecordingState and Stream State
@dataclass
class CameraStatus:
    isConnected: bool = False
    recordingState: int = CameraRecordingState.STOPPED
    isStreaming: bool = False
    videoDeviceNodeString: str = "" #example is "dev/video0"
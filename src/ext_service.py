from enum import Enum, IntEnum
from dataclasses import dataclass, field


@dataclass
class ExtServiceCfg:
    triggerErrorIfLostHeartbeat: bool = True


@dataclass
class IExtServiceInputs:
    heartbeatVal: int = 0  # USINT
    stepNum: int = 0  # INT
    errorId: int = 0  # INT
    uniqueTaskActiveId: int = 0  # DINT
    activeTaskId: int = 0  # INT
    taskStepNum: int = 0  # INT
	

@dataclass
class IExtServiceOutputs:
    heartbeatVal: int = 0  # USINT
    uniqueTaskReqId: int = 0  # DINT
    taskReqId: int = 0  # INT
    taskParam0: float = 0.0  # REAL
    taskParam1: float = 0.0  # REAL
    taskParam2: float = 0.0  # REAL
    taskParam3: float = 0.0  # REAL


@dataclass
class IExtService:
    i: IExtServiceInputs = field(default_factory=IExtServiceInputs)
    o: IExtServiceOutputs = field(default_factory=IExtServiceOutputs)


@dataclass
class ExtServiceSts:
    extServiceCfg: ExtServiceCfg = field(default_factory=ExtServiceCfg)  # read-only, references _cfg
    iExtService: IExtService = field(default_factory=IExtService)
    isConnected: bool = False


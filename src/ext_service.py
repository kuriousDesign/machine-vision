from enum import Enum, IntEnum
from dataclasses import dataclass, field


@dataclass
class ExtServiceCfg:
    triggerErrorIfLostHeartbeat: bool = True


@dataclass
class IExtServiceInputs:
    heartbeatVal: int = 0  # USINT
	

@dataclass
class IExtServiceOutputs:
    heartbeatVal: int = 0  # USINT


@dataclass
class IExtService:
    i: IExtServiceInputs = field(default_factory=IExtServiceInputs)
    o: IExtServiceOutputs = field(default_factory=IExtServiceOutputs)

@dataclass
class ExtServiceSts:
    extServiceCfg: ExtServiceCfg = field(default_factory=ExtServiceCfg)  # read-only, references _cfg
    iExtService: IExtService = field(default_factory=IExtService)
    isConnected: bool = False


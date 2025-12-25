from dataclasses import dataclass, field

@dataclass
class DeviceConstants:
    DEVICE_CHILDREN_ARRAY_LEN: int = 10
    DEVICE_FAULTCODEARRAY_LEN: int = 10  # this value should be greater than equal to children array len
    MAX_NUM_PARAMS: int = 10  # used for tasks and processes
    NUM_ACTION_TYPES: int = 6  # this includes NONE
    NUM_LOG_ENTRIES: int = 50
    MAX_NUM_OUTBOUND_AXIS_INTERLOCKS: int = 10
    UNIT_TEST_PROCESS_ID: int = 1100
    TIME_MS_AUTOCLEAR_DONE_BIT_TASK_OR_PROCESS: int = 250
    MAX_TASK_LIST_LEN: int = 20
    # MAX_NUM_ACTION_REQUESTS: int = 5

@dataclass
class ProcessData:
    # THESE PARAMETERS MUST ONLY BE WRITTEN OUTSIDE THIS FB BY method: SendProcessRequest()
    uniqueActionRequestId: int = 0
    requestId: int = 0  # processId that is being requested, specific to tasks, processes enums
    requestParamArray: list[float] = field(default_factory=lambda: [0.0] * DeviceConstants.MAX_NUM_PARAMS)  # passable parameter for the RPC Call
    senderId: int = 0  # use DeviceIds enum

    # THESE PARAMETERS ARE SET INTERNALLY
    activeId: int = 0  # active right now and not already DONE
    activeName: str = ""
    lastId: int = 0  # last completed unique id to be active (it could have ended successfully or with error)
    firstScan: bool = True
    isStepNum: int = 0  # read-only
    stepDescription: str = ""
    isDone: bool = False
    isError: bool = False
    nextStepNum: int = 0
    deviceStateThatCalled: int = 0
    deviceStepThatCalled: int = 0  # the step number that called the process, which determines where the process returns to after completion
    paramArray: list[float] = field(default_factory=lambda: [0.0] * DeviceConstants.MAX_NUM_PARAMS)  # passable parameter for the RPC Call

@dataclass
class FaultData:
    deviceId: int = 0
    code: int = 0  # this is deprecated
    msg: str = ""
    autoReset: bool = False  # if this is true, the code will be reset by the fault monitor
    resetFlag: bool = False  # used by the fault monitor to know whether to clear an fault or not
    logFlag: bool = False  # when true, this fault hasn't been logged yet
    timeStamp: int = 0  # SYSTIME representation as "ULINT"
    stepNum: int = 0  # of this device
    parentStepNum: int = 0

@dataclass
class DeviceFaultData:
    List: list[FaultData] = field(default_factory=lambda: [FaultData() for _ in range(DeviceConstants.DEVICE_FAULTCODEARRAY_LEN)])
    present: bool = False  # status
    childrenPresent: bool = False  # status that children have errors

@dataclass
class DeviceSts:
    state: int = 0  # enum for States enum, same as the boolean states in the data structure
    stepNum: int = 0
    stepDescription: str = ""
    
    colorCode: int = 0  # color to indicate the current status for HMI purposes
    statusMsg: str = ""  # status string
    
    error: bool = False  # state, device or child has an error
    killed: bool = False  # device is de-energized
    inactive: bool = False  # waiting to be reset
    resetting: bool = False  # taking action to be idle
    idle: bool = False  # ready for auto tasks
    running: bool = False  # performing an active task (excludes tasks that just involve data exchange like recipe changing)
    stopping: bool = False
    paused: bool = False  # action paused mid-task, able to be resumed (finish the task) or stopped (abandon task and back to idle or inactive)
    aborting: bool = False  # Aborting (Reacting TO E-Stop)
    done: bool = False  # finsished with task, waiting for parent to drop the request
    manual: bool = False

    idleOrError: bool = False  # useful to check for stopping
    iifkm: bool = False  # IdleOrInactiveOrFaultedOrKilledOrManual
    rri: bool = False  # ResettingOrRunningOrIdle
    ipr: bool = False  # IdleOrPausedOrRunning;
    kei: bool = False  # KilledErrorOrInactive;
    runningOrStopping: bool = False 
    
    # Children Status
    allChildrenIdle: bool = False
    allChildrenKilled: bool = False
    allChildrenInactive: bool = False
    allChildrenIdleOrError: bool = False
    
    commanderId: int = 0  # used for external control
    
    recordingLogs: bool = False

@dataclass
class DeviceStates:
    FAULTED: int = -2
    KILLED: int = -1
    INACTIVE: int = 0
    RESETTING: int = 50
    IDLE: int = 100
    RUNNING: int = 500
    STOPPING: int = 900
    PAUSED: int = 999
    ABORTING: int = 911
    DONE: int = 1000
    MANUAL: int = 2000


@dataclass
class DeviceActionRequestData:
    uniqueActionRequestId: int = 0
    senderId: int = 0
    actionType: int = 0  # ActionTypes enum
    actionId: int = 0  # could be cmd, task or processId
    paramArray: list[float] = field(default_factory=lambda: [0.0] * DeviceConstants.MAX_NUM_PARAMS)

@dataclass
class ApiOpcuaReqData:
    id: int = 0
    checkSum: int = 0
    actionRequestData: DeviceActionRequestData = field(default_factory=DeviceActionRequestData)
    sts: int = 0
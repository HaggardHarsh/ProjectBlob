from google.protobuf.internal import containers as _containers
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class FrontendEvent(_message.Message):
    __slots__ = ("timestamp_ms", "user_interaction", "skill_pill_drop", "overlay_state", "user_message", "heartbeat")
    TIMESTAMP_MS_FIELD_NUMBER: _ClassVar[int]
    USER_INTERACTION_FIELD_NUMBER: _ClassVar[int]
    SKILL_PILL_DROP_FIELD_NUMBER: _ClassVar[int]
    OVERLAY_STATE_FIELD_NUMBER: _ClassVar[int]
    USER_MESSAGE_FIELD_NUMBER: _ClassVar[int]
    HEARTBEAT_FIELD_NUMBER: _ClassVar[int]
    timestamp_ms: int
    user_interaction: UserInteraction
    skill_pill_drop: SkillPillDrop
    overlay_state: OverlayStateChange
    user_message: UserMessage
    heartbeat: HeartbeatPing
    def __init__(self, timestamp_ms: _Optional[int] = ..., user_interaction: _Optional[_Union[UserInteraction, _Mapping]] = ..., skill_pill_drop: _Optional[_Union[SkillPillDrop, _Mapping]] = ..., overlay_state: _Optional[_Union[OverlayStateChange, _Mapping]] = ..., user_message: _Optional[_Union[UserMessage, _Mapping]] = ..., heartbeat: _Optional[_Union[HeartbeatPing, _Mapping]] = ...) -> None: ...

class UserInteraction(_message.Message):
    __slots__ = ("type", "x", "y", "velocity")
    class InteractionType(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = ()
        CLICK: _ClassVar[UserInteraction.InteractionType]
        DOUBLE_CLICK: _ClassVar[UserInteraction.InteractionType]
        PET: _ClassVar[UserInteraction.InteractionType]
        POKE: _ClassVar[UserInteraction.InteractionType]
        RIGHT_CLICK: _ClassVar[UserInteraction.InteractionType]
    CLICK: UserInteraction.InteractionType
    DOUBLE_CLICK: UserInteraction.InteractionType
    PET: UserInteraction.InteractionType
    POKE: UserInteraction.InteractionType
    RIGHT_CLICK: UserInteraction.InteractionType
    TYPE_FIELD_NUMBER: _ClassVar[int]
    X_FIELD_NUMBER: _ClassVar[int]
    Y_FIELD_NUMBER: _ClassVar[int]
    VELOCITY_FIELD_NUMBER: _ClassVar[int]
    type: UserInteraction.InteractionType
    x: int
    y: int
    velocity: float
    def __init__(self, type: _Optional[_Union[UserInteraction.InteractionType, str]] = ..., x: _Optional[int] = ..., y: _Optional[int] = ..., velocity: _Optional[float] = ...) -> None: ...

class SkillPillDrop(_message.Message):
    __slots__ = ("file_path", "skill_name", "file_hash")
    FILE_PATH_FIELD_NUMBER: _ClassVar[int]
    SKILL_NAME_FIELD_NUMBER: _ClassVar[int]
    FILE_HASH_FIELD_NUMBER: _ClassVar[int]
    file_path: str
    skill_name: str
    file_hash: bytes
    def __init__(self, file_path: _Optional[str] = ..., skill_name: _Optional[str] = ..., file_hash: _Optional[bytes] = ...) -> None: ...

class OverlayStateChange(_message.Message):
    __slots__ = ("is_visible", "is_minimized", "screen_width", "screen_height")
    IS_VISIBLE_FIELD_NUMBER: _ClassVar[int]
    IS_MINIMIZED_FIELD_NUMBER: _ClassVar[int]
    SCREEN_WIDTH_FIELD_NUMBER: _ClassVar[int]
    SCREEN_HEIGHT_FIELD_NUMBER: _ClassVar[int]
    is_visible: bool
    is_minimized: bool
    screen_width: int
    screen_height: int
    def __init__(self, is_visible: _Optional[bool] = ..., is_minimized: _Optional[bool] = ..., screen_width: _Optional[int] = ..., screen_height: _Optional[int] = ...) -> None: ...

class UserMessage(_message.Message):
    __slots__ = ("text", "attachments", "conversation_id")
    TEXT_FIELD_NUMBER: _ClassVar[int]
    ATTACHMENTS_FIELD_NUMBER: _ClassVar[int]
    CONVERSATION_ID_FIELD_NUMBER: _ClassVar[int]
    text: str
    attachments: _containers.RepeatedScalarFieldContainer[str]
    conversation_id: str
    def __init__(self, text: _Optional[str] = ..., attachments: _Optional[_Iterable[str]] = ..., conversation_id: _Optional[str] = ...) -> None: ...

class HeartbeatPing(_message.Message):
    __slots__ = ("frontend_uptime_ms",)
    FRONTEND_UPTIME_MS_FIELD_NUMBER: _ClassVar[int]
    frontend_uptime_ms: int
    def __init__(self, frontend_uptime_ms: _Optional[int] = ...) -> None: ...

class BackendEvent(_message.Message):
    __slots__ = ("timestamp_ms", "emote", "state", "notification", "skill_ack", "privacy", "color_shift", "heartbeat", "position_hint")
    TIMESTAMP_MS_FIELD_NUMBER: _ClassVar[int]
    EMOTE_FIELD_NUMBER: _ClassVar[int]
    STATE_FIELD_NUMBER: _ClassVar[int]
    NOTIFICATION_FIELD_NUMBER: _ClassVar[int]
    SKILL_ACK_FIELD_NUMBER: _ClassVar[int]
    PRIVACY_FIELD_NUMBER: _ClassVar[int]
    COLOR_SHIFT_FIELD_NUMBER: _ClassVar[int]
    HEARTBEAT_FIELD_NUMBER: _ClassVar[int]
    POSITION_HINT_FIELD_NUMBER: _ClassVar[int]
    timestamp_ms: int
    emote: EmoteCommand
    state: StateCommand
    notification: NotificationBubble
    skill_ack: SkillAcknowledgment
    privacy: PrivacyShieldEvent
    color_shift: ColorShiftEvent
    heartbeat: HeartbeatPong
    position_hint: BlobPositionHint
    def __init__(self, timestamp_ms: _Optional[int] = ..., emote: _Optional[_Union[EmoteCommand, _Mapping]] = ..., state: _Optional[_Union[StateCommand, _Mapping]] = ..., notification: _Optional[_Union[NotificationBubble, _Mapping]] = ..., skill_ack: _Optional[_Union[SkillAcknowledgment, _Mapping]] = ..., privacy: _Optional[_Union[PrivacyShieldEvent, _Mapping]] = ..., color_shift: _Optional[_Union[ColorShiftEvent, _Mapping]] = ..., heartbeat: _Optional[_Union[HeartbeatPong, _Mapping]] = ..., position_hint: _Optional[_Union[BlobPositionHint, _Mapping]] = ...) -> None: ...

class EmoteCommand(_message.Message):
    __slots__ = ("emote", "intensity", "duration_ms", "trigger_reason", "secondary_emote", "blend")
    class Emote(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = ()
        IDLE: _ClassVar[EmoteCommand.Emote]
        HAPPY: _ClassVar[EmoteCommand.Emote]
        TIRED: _ClassVar[EmoteCommand.Emote]
        EXCITED: _ClassVar[EmoteCommand.Emote]
        THINKING: _ClassVar[EmoteCommand.Emote]
        OFFER_COFFEE: _ClassVar[EmoteCommand.Emote]
        CELEBRATE: _ClassVar[EmoteCommand.Emote]
        SHY: _ClassVar[EmoteCommand.Emote]
        SLEEPING: _ClassVar[EmoteCommand.Emote]
        EATING: _ClassVar[EmoteCommand.Emote]
        CONFUSED: _ClassVar[EmoteCommand.Emote]
        PROUD: _ClassVar[EmoteCommand.Emote]
        WORRIED: _ClassVar[EmoteCommand.Emote]
        PLAYFUL: _ClassVar[EmoteCommand.Emote]
        SAD: _ClassVar[EmoteCommand.Emote]
        ANGRY: _ClassVar[EmoteCommand.Emote]
        WORKING: _ClassVar[EmoteCommand.Emote]
        DEEP_THINKING: _ClassVar[EmoteCommand.Emote]
        LISTENING: _ClassVar[EmoteCommand.Emote]
        SHOCKED: _ClassVar[EmoteCommand.Emote]
        MELTING: _ClassVar[EmoteCommand.Emote]
        ERROR: _ClassVar[EmoteCommand.Emote]
        SUCCESS: _ClassVar[EmoteCommand.Emote]
        WAITING: _ClassVar[EmoteCommand.Emote]
    IDLE: EmoteCommand.Emote
    HAPPY: EmoteCommand.Emote
    TIRED: EmoteCommand.Emote
    EXCITED: EmoteCommand.Emote
    THINKING: EmoteCommand.Emote
    OFFER_COFFEE: EmoteCommand.Emote
    CELEBRATE: EmoteCommand.Emote
    SHY: EmoteCommand.Emote
    SLEEPING: EmoteCommand.Emote
    EATING: EmoteCommand.Emote
    CONFUSED: EmoteCommand.Emote
    PROUD: EmoteCommand.Emote
    WORRIED: EmoteCommand.Emote
    PLAYFUL: EmoteCommand.Emote
    SAD: EmoteCommand.Emote
    ANGRY: EmoteCommand.Emote
    WORKING: EmoteCommand.Emote
    DEEP_THINKING: EmoteCommand.Emote
    LISTENING: EmoteCommand.Emote
    SHOCKED: EmoteCommand.Emote
    MELTING: EmoteCommand.Emote
    ERROR: EmoteCommand.Emote
    SUCCESS: EmoteCommand.Emote
    WAITING: EmoteCommand.Emote
    EMOTE_FIELD_NUMBER: _ClassVar[int]
    INTENSITY_FIELD_NUMBER: _ClassVar[int]
    DURATION_MS_FIELD_NUMBER: _ClassVar[int]
    TRIGGER_REASON_FIELD_NUMBER: _ClassVar[int]
    SECONDARY_EMOTE_FIELD_NUMBER: _ClassVar[int]
    BLEND_FIELD_NUMBER: _ClassVar[int]
    emote: EmoteCommand.Emote
    intensity: float
    duration_ms: int
    trigger_reason: str
    secondary_emote: EmoteCommand.Emote
    blend: float
    def __init__(self, emote: _Optional[_Union[EmoteCommand.Emote, str]] = ..., intensity: _Optional[float] = ..., duration_ms: _Optional[int] = ..., trigger_reason: _Optional[str] = ..., secondary_emote: _Optional[_Union[EmoteCommand.Emote, str]] = ..., blend: _Optional[float] = ...) -> None: ...

class StateCommand(_message.Message):
    __slots__ = ("state", "params")
    class State(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = ()
        NORMAL: _ClassVar[StateCommand.State]
        SLEEP: _ClassVar[StateCommand.State]
        CRAWL: _ClassVar[StateCommand.State]
        DIVIDE: _ClassVar[StateCommand.State]
        MERGE: _ClassVar[StateCommand.State]
        HIDE: _ClassVar[StateCommand.State]
        BLINDFOLD: _ClassVar[StateCommand.State]
        BOUNCE: _ClassVar[StateCommand.State]
    NORMAL: StateCommand.State
    SLEEP: StateCommand.State
    CRAWL: StateCommand.State
    DIVIDE: StateCommand.State
    MERGE: StateCommand.State
    HIDE: StateCommand.State
    BLINDFOLD: StateCommand.State
    BOUNCE: StateCommand.State
    class ParamsEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: str
        def __init__(self, key: _Optional[str] = ..., value: _Optional[str] = ...) -> None: ...
    STATE_FIELD_NUMBER: _ClassVar[int]
    PARAMS_FIELD_NUMBER: _ClassVar[int]
    state: StateCommand.State
    params: _containers.ScalarMap[str, str]
    def __init__(self, state: _Optional[_Union[StateCommand.State, str]] = ..., params: _Optional[_Mapping[str, str]] = ...) -> None: ...

class NotificationBubble(_message.Message):
    __slots__ = ("text", "display_ms", "priority", "actionable", "action_label")
    class Priority(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = ()
        LOW: _ClassVar[NotificationBubble.Priority]
        NORMAL: _ClassVar[NotificationBubble.Priority]
        HIGH: _ClassVar[NotificationBubble.Priority]
    LOW: NotificationBubble.Priority
    NORMAL: NotificationBubble.Priority
    HIGH: NotificationBubble.Priority
    TEXT_FIELD_NUMBER: _ClassVar[int]
    DISPLAY_MS_FIELD_NUMBER: _ClassVar[int]
    PRIORITY_FIELD_NUMBER: _ClassVar[int]
    ACTIONABLE_FIELD_NUMBER: _ClassVar[int]
    ACTION_LABEL_FIELD_NUMBER: _ClassVar[int]
    text: str
    display_ms: int
    priority: NotificationBubble.Priority
    actionable: bool
    action_label: str
    def __init__(self, text: _Optional[str] = ..., display_ms: _Optional[int] = ..., priority: _Optional[_Union[NotificationBubble.Priority, str]] = ..., actionable: _Optional[bool] = ..., action_label: _Optional[str] = ...) -> None: ...

class SkillAcknowledgment(_message.Message):
    __slots__ = ("skill_name", "success", "description", "error_message")
    SKILL_NAME_FIELD_NUMBER: _ClassVar[int]
    SUCCESS_FIELD_NUMBER: _ClassVar[int]
    DESCRIPTION_FIELD_NUMBER: _ClassVar[int]
    ERROR_MESSAGE_FIELD_NUMBER: _ClassVar[int]
    skill_name: str
    success: bool
    description: str
    error_message: str
    def __init__(self, skill_name: _Optional[str] = ..., success: _Optional[bool] = ..., description: _Optional[str] = ..., error_message: _Optional[str] = ...) -> None: ...

class PrivacyShieldEvent(_message.Message):
    __slots__ = ("activated", "reason", "blocked_process")
    ACTIVATED_FIELD_NUMBER: _ClassVar[int]
    REASON_FIELD_NUMBER: _ClassVar[int]
    BLOCKED_PROCESS_FIELD_NUMBER: _ClassVar[int]
    activated: bool
    reason: str
    blocked_process: str
    def __init__(self, activated: _Optional[bool] = ..., reason: _Optional[str] = ..., blocked_process: _Optional[str] = ...) -> None: ...

class ColorShiftEvent(_message.Message):
    __slots__ = ("r", "g", "b", "a", "transition_ms")
    R_FIELD_NUMBER: _ClassVar[int]
    G_FIELD_NUMBER: _ClassVar[int]
    B_FIELD_NUMBER: _ClassVar[int]
    A_FIELD_NUMBER: _ClassVar[int]
    TRANSITION_MS_FIELD_NUMBER: _ClassVar[int]
    r: float
    g: float
    b: float
    a: float
    transition_ms: int
    def __init__(self, r: _Optional[float] = ..., g: _Optional[float] = ..., b: _Optional[float] = ..., a: _Optional[float] = ..., transition_ms: _Optional[int] = ...) -> None: ...

class HeartbeatPong(_message.Message):
    __slots__ = ("backend_uptime_ms", "memory_usage_mb", "llm_loaded", "privacy_shield_active")
    BACKEND_UPTIME_MS_FIELD_NUMBER: _ClassVar[int]
    MEMORY_USAGE_MB_FIELD_NUMBER: _ClassVar[int]
    LLM_LOADED_FIELD_NUMBER: _ClassVar[int]
    PRIVACY_SHIELD_ACTIVE_FIELD_NUMBER: _ClassVar[int]
    backend_uptime_ms: int
    memory_usage_mb: float
    llm_loaded: bool
    privacy_shield_active: bool
    def __init__(self, backend_uptime_ms: _Optional[int] = ..., memory_usage_mb: _Optional[float] = ..., llm_loaded: _Optional[bool] = ..., privacy_shield_active: _Optional[bool] = ...) -> None: ...

class BlobPositionHint(_message.Message):
    __slots__ = ("anchor", "offset_x", "offset_y")
    class Anchor(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = ()
        BOTTOM_RIGHT: _ClassVar[BlobPositionHint.Anchor]
        BOTTOM_LEFT: _ClassVar[BlobPositionHint.Anchor]
        TOP_RIGHT: _ClassVar[BlobPositionHint.Anchor]
        TOP_LEFT: _ClassVar[BlobPositionHint.Anchor]
        CENTER: _ClassVar[BlobPositionHint.Anchor]
        FOLLOW_CURSOR: _ClassVar[BlobPositionHint.Anchor]
    BOTTOM_RIGHT: BlobPositionHint.Anchor
    BOTTOM_LEFT: BlobPositionHint.Anchor
    TOP_RIGHT: BlobPositionHint.Anchor
    TOP_LEFT: BlobPositionHint.Anchor
    CENTER: BlobPositionHint.Anchor
    FOLLOW_CURSOR: BlobPositionHint.Anchor
    ANCHOR_FIELD_NUMBER: _ClassVar[int]
    OFFSET_X_FIELD_NUMBER: _ClassVar[int]
    OFFSET_Y_FIELD_NUMBER: _ClassVar[int]
    anchor: BlobPositionHint.Anchor
    offset_x: int
    offset_y: int
    def __init__(self, anchor: _Optional[_Union[BlobPositionHint.Anchor, str]] = ..., offset_x: _Optional[int] = ..., offset_y: _Optional[int] = ...) -> None: ...

class SkillRegistration(_message.Message):
    __slots__ = ("name", "description", "module_path", "required_permissions", "metadata")
    NAME_FIELD_NUMBER: _ClassVar[int]
    DESCRIPTION_FIELD_NUMBER: _ClassVar[int]
    MODULE_PATH_FIELD_NUMBER: _ClassVar[int]
    REQUIRED_PERMISSIONS_FIELD_NUMBER: _ClassVar[int]
    METADATA_FIELD_NUMBER: _ClassVar[int]
    name: str
    description: str
    module_path: str
    required_permissions: _containers.RepeatedScalarFieldContainer[str]
    metadata: SkillMetadata
    def __init__(self, name: _Optional[str] = ..., description: _Optional[str] = ..., module_path: _Optional[str] = ..., required_permissions: _Optional[_Iterable[str]] = ..., metadata: _Optional[_Union[SkillMetadata, _Mapping]] = ...) -> None: ...

class SkillMetadata(_message.Message):
    __slots__ = ("icon", "color_hex", "author", "version", "trigger_phrases")
    ICON_FIELD_NUMBER: _ClassVar[int]
    COLOR_HEX_FIELD_NUMBER: _ClassVar[int]
    AUTHOR_FIELD_NUMBER: _ClassVar[int]
    VERSION_FIELD_NUMBER: _ClassVar[int]
    TRIGGER_PHRASES_FIELD_NUMBER: _ClassVar[int]
    icon: str
    color_hex: str
    author: str
    version: str
    trigger_phrases: _containers.RepeatedScalarFieldContainer[str]
    def __init__(self, icon: _Optional[str] = ..., color_hex: _Optional[str] = ..., author: _Optional[str] = ..., version: _Optional[str] = ..., trigger_phrases: _Optional[_Iterable[str]] = ...) -> None: ...

class SkillRegistrationResponse(_message.Message):
    __slots__ = ("success", "error", "skill_id")
    SUCCESS_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    SKILL_ID_FIELD_NUMBER: _ClassVar[int]
    success: bool
    error: str
    skill_id: str
    def __init__(self, success: _Optional[bool] = ..., error: _Optional[str] = ..., skill_id: _Optional[str] = ...) -> None: ...

class BlobState(_message.Message):
    __slots__ = ("current_emote", "current_state", "loaded_skills", "privacy_shield_active", "energy_level", "uptime_ms", "memories_stored", "last_response")
    CURRENT_EMOTE_FIELD_NUMBER: _ClassVar[int]
    CURRENT_STATE_FIELD_NUMBER: _ClassVar[int]
    LOADED_SKILLS_FIELD_NUMBER: _ClassVar[int]
    PRIVACY_SHIELD_ACTIVE_FIELD_NUMBER: _ClassVar[int]
    ENERGY_LEVEL_FIELD_NUMBER: _ClassVar[int]
    UPTIME_MS_FIELD_NUMBER: _ClassVar[int]
    MEMORIES_STORED_FIELD_NUMBER: _ClassVar[int]
    LAST_RESPONSE_FIELD_NUMBER: _ClassVar[int]
    current_emote: EmoteCommand.Emote
    current_state: StateCommand.State
    loaded_skills: _containers.RepeatedScalarFieldContainer[str]
    privacy_shield_active: bool
    energy_level: float
    uptime_ms: int
    memories_stored: int
    last_response: AssistantResponse
    def __init__(self, current_emote: _Optional[_Union[EmoteCommand.Emote, str]] = ..., current_state: _Optional[_Union[StateCommand.State, str]] = ..., loaded_skills: _Optional[_Iterable[str]] = ..., privacy_shield_active: _Optional[bool] = ..., energy_level: _Optional[float] = ..., uptime_ms: _Optional[int] = ..., memories_stored: _Optional[int] = ..., last_response: _Optional[_Union[AssistantResponse, _Mapping]] = ...) -> None: ...

class AssistantResponse(_message.Message):
    __slots__ = ("text", "emote", "skills_used")
    TEXT_FIELD_NUMBER: _ClassVar[int]
    EMOTE_FIELD_NUMBER: _ClassVar[int]
    SKILLS_USED_FIELD_NUMBER: _ClassVar[int]
    text: str
    emote: EmoteCommand
    skills_used: _containers.RepeatedCompositeFieldContainer[SkillInvocation]
    def __init__(self, text: _Optional[str] = ..., emote: _Optional[_Union[EmoteCommand, _Mapping]] = ..., skills_used: _Optional[_Iterable[_Union[SkillInvocation, _Mapping]]] = ...) -> None: ...

class SkillInvocation(_message.Message):
    __slots__ = ("skill_name", "tool_name", "result_summary", "success")
    SKILL_NAME_FIELD_NUMBER: _ClassVar[int]
    TOOL_NAME_FIELD_NUMBER: _ClassVar[int]
    RESULT_SUMMARY_FIELD_NUMBER: _ClassVar[int]
    SUCCESS_FIELD_NUMBER: _ClassVar[int]
    skill_name: str
    tool_name: str
    result_summary: str
    success: bool
    def __init__(self, skill_name: _Optional[str] = ..., tool_name: _Optional[str] = ..., result_summary: _Optional[str] = ..., success: _Optional[bool] = ...) -> None: ...

class ConfigUpdate(_message.Message):
    __slots__ = ("settings",)
    class SettingsEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: str
        def __init__(self, key: _Optional[str] = ..., value: _Optional[str] = ...) -> None: ...
    SETTINGS_FIELD_NUMBER: _ClassVar[int]
    settings: _containers.ScalarMap[str, str]
    def __init__(self, settings: _Optional[_Mapping[str, str]] = ...) -> None: ...

class ConfigUpdateResponse(_message.Message):
    __slots__ = ("success", "error", "effective_config")
    class EffectiveConfigEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: str
        def __init__(self, key: _Optional[str] = ..., value: _Optional[str] = ...) -> None: ...
    SUCCESS_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    EFFECTIVE_CONFIG_FIELD_NUMBER: _ClassVar[int]
    success: bool
    error: str
    effective_config: _containers.ScalarMap[str, str]
    def __init__(self, success: _Optional[bool] = ..., error: _Optional[str] = ..., effective_config: _Optional[_Mapping[str, str]] = ...) -> None: ...

class Empty(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

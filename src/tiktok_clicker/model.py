"""The capture journal's schema: every line of a journal is one `Entry`."""

from enum import StrEnum

from msgspec import Struct


class Mode(StrEnum):
	C = "C"
	T = "T"


class Button(StrEnum):
	UP = "up"
	CENTER = "center"
	DOWN = "down"


class Verdict(StrEnum):
	KEEP = "keep"
	REDO = "redo"
	QUIT = "quit"


class InitiatorKeys(StrEnum):
	ENC_ID = "enc-id"
	ID = "id"


class Tagged(Struct, frozen=True, tag_field="kind"):
	pass


class SwitchMode(Tagged, frozen=True, tag="switch-mode"):
	mode: Mode


class Press(Tagged, frozen=True, tag="press"):
	mode: Mode
	button: Button
	count: int


class Hold(Tagged, frozen=True, tag="hold"):
	mode: Mode
	button: Button
	seconds: int


type Step = SwitchMode | Press | Hold


class Value(Tagged, frozen=True, tag="value"):
	hex: str


class ReadFailed(Tagged, frozen=True, tag="read-failed"):
	error: str


class NotRead(Tagged, frozen=True, tag="not-read"):
	pass


type Read = Value | ReadFailed | NotRead


class GattDescriptor(Struct, frozen=True):
	handle: int
	uuid: str
	name: str
	read: Read


class GattCharacteristic(Struct, frozen=True):
	handle: int
	uuid: str
	name: str
	properties: str
	read: Read
	descriptors: tuple[GattDescriptor, ...]


class GattService(Struct, frozen=True):
	handle: int
	end_handle: int
	uuid: str
	name: str
	characteristics: tuple[GattCharacteristic, ...]


class Started(Tagged, frozen=True, tag="started"):
	t: float
	utc: str
	version: str
	hci: str
	target: str
	initiator_keys: InitiatorKeys = InitiatorKeys.ENC_ID


class Connected(Tagged, frozen=True, tag="connected"):
	t: float
	peer: str
	gatt: tuple[GattService, ...]


class LinkFailed(Tagged, frozen=True, tag="link-failed"):
	t: float
	error: str


class Report(Tagged, frozen=True, tag="report"):
	t: float
	handle: int
	report_id: int
	hex: str


class Indication(Tagged, frozen=True, tag="indication"):
	t: float
	handle: int
	hex: str


class Disconnected(Tagged, frozen=True, tag="disconnected"):
	t: float
	reason: int


class StepBegan(Tagged, frozen=True, tag="step-began"):
	t: float
	step: Step


class StepEnded(Tagged, frozen=True, tag="step-ended"):
	t: float
	step: Step
	verdict: Verdict
	note: str


type DeviceEvent = Report | Indication | Disconnected

type Entry = (
	Started | Connected | LinkFailed | Report | Indication | Disconnected | StepBegan | StepEnded
)

from typing import Final

from tiktok_clicker.gatt import PROTOCOL_MODE, REPORT, REPORT_MAP, REPORT_REFERENCE
from tiktok_clicker.model import (
	GattCharacteristic,
	GattDescriptor,
	GattService,
	NotRead,
	Read,
	Value,
)

CCCD: Final = "2902"


def report(handle: int, reference: str) -> GattCharacteristic:
	return GattCharacteristic(
		handle=handle,
		uuid=REPORT,
		name="Report",
		properties="READ|NOTIFY",
		read=Value(hex=""),
		descriptors=(
			GattDescriptor(handle=handle + 1, uuid=CCCD, name="", read=NotRead()),
			GattDescriptor(
				handle=handle + 2, uuid=REPORT_REFERENCE, name="", read=Value(hex=reference)
			),
		),
	)


def hid_service(protocol_mode: Read, report_map: Read) -> GattService:
	"""The F3 ring's HID service handle layout as Bumble discovered it."""
	return GattService(
		handle=0x000F,
		end_handle=0x002B,
		uuid="1812",
		name="Human Interface Device",
		characteristics=(
			GattCharacteristic(
				handle=0x0011,
				uuid=PROTOCOL_MODE,
				name="Protocol Mode",
				properties="READ|WRITE_WITHOUT_RESPONSE",
				read=protocol_mode,
				descriptors=(),
			),
			report(0x0013, "0201"),
			report(0x0017, "0301"),
			report(0x001B, "0401"),
			report(0x001F, "0501"),
			report(0x0023, "0502"),
			GattCharacteristic(
				handle=0x0027,
				uuid=REPORT_MAP,
				name="Report Map",
				properties="READ",
				read=report_map,
				descriptors=(),
			),
		),
	)

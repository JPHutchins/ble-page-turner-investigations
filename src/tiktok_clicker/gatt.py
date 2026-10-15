"""Queries over a recorded GATT snapshot."""

from enum import IntEnum
from typing import TYPE_CHECKING, Final, NamedTuple

from bumble.gatt import (
	GATT_PROTOCOL_MODE_CHARACTERISTIC,
	GATT_REPORT_CHARACTERISTIC,
	GATT_REPORT_MAP_CHARACTERISTIC,
	GATT_REPORT_REFERENCE_DESCRIPTOR,
)

from tiktok_clicker.model import GattCharacteristic, GattService, NotRead, Read, ReadFailed, Value

if TYPE_CHECKING:
	from collections.abc import Iterable, Iterator

	from bumble.core import UUID


def uuid_text(uuid: UUID) -> str:
	"""The form a snapshot records UUIDs in.

	>>> uuid_text(GATT_REPORT_MAP_CHARACTERISTIC)
	'2A4B'
	"""
	return uuid.to_hex_str("-")


REPORT: Final = uuid_text(GATT_REPORT_CHARACTERISTIC)
REPORT_MAP: Final = uuid_text(GATT_REPORT_MAP_CHARACTERISTIC)
REPORT_REFERENCE: Final = uuid_text(GATT_REPORT_REFERENCE_DESCRIPTOR)
PROTOCOL_MODE: Final = uuid_text(GATT_PROTOCOL_MODE_CHARACTERISTIC)
BOOT_PROTOCOL: Final = b"\x00"


class HidReportType(IntEnum):
	INPUT = 1
	OUTPUT = 2
	FEATURE = 3


class ReportReference(NamedTuple):
	report_id: int
	report_type: int


def value_bytes(read: Read) -> bytes | None:
	match read:
		case Value(hex=hex_digits):
			return bytes.fromhex(hex_digits)
		case ReadFailed() | NotRead():
			return None


def characteristics(gatt: Iterable[GattService]) -> Iterator[GattCharacteristic]:
	return (characteristic for service in gatt for characteristic in service.characteristics)


def report_reference(characteristic: GattCharacteristic) -> ReportReference | None:
	return next(
		(
			ReportReference(report_id=value[0], report_type=value[1])
			for descriptor in characteristic.descriptors
			if descriptor.uuid == REPORT_REFERENCE
			and (value := value_bytes(descriptor.read)) is not None
			and len(value) >= 2
		),
		None,
	)


def input_report_ids(gatt: Iterable[GattService]) -> dict[int, int]:
	"""Report characteristic value handle to the report ID its notifications carry."""
	return {
		characteristic.handle: reference.report_id
		for characteristic in characteristics(gatt)
		if characteristic.uuid == REPORT
		and (reference := report_reference(characteristic)) is not None
		and reference.report_type == HidReportType.INPUT
	}


def report_maps(gatt: Iterable[GattService]) -> tuple[bytes, ...]:
	return tuple(
		value
		for characteristic in characteristics(gatt)
		if characteristic.uuid == REPORT_MAP
		and (value := value_bytes(characteristic.read)) is not None
	)


def boot_protocol_handles(gatt: Iterable[GattService]) -> tuple[int, ...]:
	return tuple(
		characteristic.handle
		for characteristic in characteristics(gatt)
		if characteristic.uuid == PROTOCOL_MODE
		and value_bytes(characteristic.read) == BOOT_PROTOCOL
	)

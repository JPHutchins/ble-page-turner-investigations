"""Human-readable text for journal entries."""

from collections import Counter
from typing import TYPE_CHECKING

from page_turner.gatt import input_report_ids, report_maps
from page_turner.model import (
	Connected,
	DeviceEvent,
	Disconnected,
	Entry,
	GattService,
	Indication,
	LinkFailed,
	NotRead,
	Read,
	ReadFailed,
	Report,
	Started,
	StepBegan,
	StepEnded,
	Value,
)
from page_turner.plan import instruction

if TYPE_CHECKING:
	from collections.abc import Iterable


def spaced_hex(hex_digits: str) -> str:
	return bytes.fromhex(hex_digits).hex(" ")


def describe(entry: Entry) -> str:
	"""One line per entry.

	>>> describe(Report(t=2.5, handle=0x17, report_id=4, hex="07f401"))
	'   2.500s report id=4 h=0x0017: 07 f4 01'
	>>> describe(Disconnected(t=3.0, reason=0x13))
	'   3.000s disconnected (reason 0x13)'
	"""
	match entry:
		case Started(utc=utc, version=version, hci=hci, target=target):
			return f"started {utc} page-turner {version}, hci {hci}, target {target}"
		case Connected(t=t, peer=peer, gatt=gatt):
			return (
				f"{t:8.3f}s linked to {peer}: input reports {sorted(input_report_ids(gatt).values())}, "
				f"report map {[len(value) for value in report_maps(gatt)]} bytes"
			)
		case LinkFailed(t=t, error=error):
			return f"{t:8.3f}s link failed: {error}"
		case Report(t=t, handle=handle, report_id=report_id, hex=hex_digits):
			return f"{t:8.3f}s report id={report_id} h=0x{handle:04x}: {spaced_hex(hex_digits)}"
		case Indication(t=t, handle=handle, hex=hex_digits):
			return f"{t:8.3f}s indication h=0x{handle:04x}: {spaced_hex(hex_digits)}"
		case Disconnected(t=t, reason=reason):
			return f"{t:8.3f}s disconnected (reason 0x{reason:02x})"
		case StepBegan(t=t, step=step):
			return f"{t:8.3f}s >>> {instruction(step)}"
		case StepEnded(t=t, verdict=verdict, note=note):
			return f"{t:8.3f}s <<< {verdict}" + (f": {note}" if note else "")


def summarize(events: Iterable[DeviceEvent]) -> str:
	"""What a step produced, so a press that registered nothing can be redone.

	>>> summarize(())
	'no reports received'
	>>> summarize((Report(t=0, handle=0x17, report_id=4, hex="00"),) * 2 + (Disconnected(t=1, reason=8),))
	'2 reports (id 4 x2), then the ring disconnected'
	"""
	materialized = tuple(events)
	counts = Counter(event.report_id for event in materialized if isinstance(event, Report))
	reports = (
		f"{counts.total()} reports ({', '.join(f'id {rid} x{n}' for rid, n in sorted(counts.items()))})"
		if counts
		else "no reports received"
	)
	return reports + (
		", then the ring disconnected"
		if any(isinstance(event, Disconnected) for event in materialized)
		else ""
	)


def describe_read(read: Read) -> str:
	match read:
		case Value(hex=hex_digits):
			return f" = {spaced_hex(hex_digits)}"
		case ReadFailed(error=error):
			return f" read failed: {error}"
		case NotRead():
			return ""


def describe_gatt(gatt: Iterable[GattService]) -> str:
	return "\n".join(
		line
		for service in gatt
		for line in (
			f"service {service.uuid} {service.name} [0x{service.handle:04x}-0x{service.end_handle:04x}]",
			*(
				line
				for characteristic in service.characteristics
				for line in (
					(
						f"  0x{characteristic.handle:04x} {characteristic.uuid} {characteristic.name}"
						f" ({characteristic.properties}){describe_read(characteristic.read)}"
					),
					*(
						(
							f"    0x{descriptor.handle:04x} {descriptor.uuid} {descriptor.name}"
							f"{describe_read(descriptor.read)}"
						)
						for descriptor in characteristic.descriptors
					),
				)
			),
		)
	)


def render_journal(entries: Iterable[Entry]) -> str:
	return "\n".join(
		f"{describe(entry)}\n{describe_gatt(entry.gatt)}"
		if isinstance(entry, Connected)
		else describe(entry)
		for entry in entries
	)

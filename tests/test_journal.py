from typing import TYPE_CHECKING, Final

from ring_gatt import hid_service

from tiktok_clicker.journal import decode_entries, encode_entry, journal, read_journal
from tiktok_clicker.model import (
	Button,
	Connected,
	Disconnected,
	Entry,
	Hold,
	Indication,
	LinkFailed,
	Mode,
	Press,
	ReadFailed,
	Report,
	Started,
	StepBegan,
	StepEnded,
	SwitchMode,
	Value,
	Verdict,
)

if TYPE_CHECKING:
	from pathlib import Path

EVERY_KIND: Final[tuple[Entry, ...]] = (
	Started(
		t=0.0, utc="2026-10-14T00:00:00+00:00", version="0.1.0", hci="serial:COM3", target="F3"
	),
	Connected(
		t=1.0, peer="EB:80:03:88:70:8B", gatt=(hid_service(Value(hex="01"), ReadFailed(error="x")),)
	),
	LinkFailed(t=1.5, error="TimeoutError()"),
	StepBegan(t=2.0, step=SwitchMode(mode=Mode.T)),
	Report(t=2.1, handle=0x1B, report_id=4, hex="07f401f401"),
	Indication(t=2.2, handle=0x03, hex="0f002b00"),
	StepEnded(
		t=2.3, step=Press(mode=Mode.T, button=Button.UP, count=3), verdict=Verdict.REDO, note=""
	),
	StepEnded(
		t=2.4,
		step=Hold(mode=Mode.C, button=Button.DOWN, seconds=2),
		verdict=Verdict.KEEP,
		note="hi",
	),
	Disconnected(t=3.0, reason=0x13),
)


def test_every_entry_kind_round_trips() -> None:
	assert decode_entries(b"".join(encode_entry(entry) for entry in EVERY_KIND)) == EVERY_KIND


def test_journal_appends_across_sessions(tmp_path: Path) -> None:
	path = tmp_path / "nested" / "capture.jsonl"
	with journal(path) as append:
		append(EVERY_KIND[0])
	with journal(path) as append:
		append(EVERY_KIND[-1])
	assert read_journal(path) == (EVERY_KIND[0], EVERY_KIND[-1])

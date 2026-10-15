import asyncio
from typing import Final

from tiktok_clicker.guided import StepContext, Terminal
from tiktok_clicker.model import DeviceEvent, Disconnected, Entry, Report
from tiktok_clicker.soak import Dropped, Held, describe_soak, hold

TAP: Final = Report(t=1.0, handle=0x1B, report_id=3, hex="07")


def discard(_entry: Entry) -> None:
	return None


def context_with(*events: DeviceEvent) -> StepContext:
	inbox = asyncio.Queue[DeviceEvent]()
	for event in events:
		inbox.put_nowait(event)
	return StepContext(discard, inbox, lambda: 2.5, Terminal())


async def test_hold_reports_when_the_ring_drops_the_link() -> None:
	assert await hold(context_with(TAP, Disconnected(t=32.5, reason=0x13)), 45.0) == Dropped(
		after_seconds=30.0, reason=0x13
	)


async def test_hold_reports_a_held_link_when_time_runs_out() -> None:
	assert await hold(context_with(TAP), 0.01) == Held(seconds=0.01)


def test_describe_soak() -> None:
	assert describe_soak(Held(seconds=45.0)) == "Held the link for 45 s."
	assert (
		describe_soak(Dropped(after_seconds=27.25, reason=0x13))
		== "The ring dropped the link 27.2 s after linking (reason 0x13)."
	)

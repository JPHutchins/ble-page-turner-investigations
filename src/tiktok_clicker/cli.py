"""Command line interface."""

import asyncio
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import partial
from importlib.metadata import version
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Final

from cyclopts import App, Parameter

from tiktok_clicker.guided import Session, StepContext, Terminal, router, run_guided
from tiktok_clicker.journal import journal, read_journal
from tiktok_clicker.link import hci_device
from tiktok_clicker.model import Button, DeviceEvent, InitiatorKeys, Mode, Started
from tiktok_clicker.plan import guided_plan
from tiktok_clicker.render import render_journal
from tiktok_clicker.soak import describe_soak, soak_link

if TYPE_CHECKING:
	from collections.abc import AsyncGenerator

app: Final = App(
	name="tiktok-clicker",
	help="Probe BLE HID ring remotes over a Bumble HCI controller.",
	version=version("tiktok-clicker"),
)

GUIDE: Final = """
Each step asks you to do something with the ring. Do it, then press Enter.
Every report the ring sends is printed as it arrives, and summarized at the end of the step.
Then press Enter to keep the step, r to redo it, q to quit, or type a note to keep with it.
"""

SOAK: Final = """
Wake the ring, then leave it alone: the link is held idle to see whether the ring drops it.
"""


@Parameter(name="*")
@dataclass(frozen=True, kw_only=True)
class LinkOptions:
	hci: Annotated[
		str,
		Parameter(
			env_var="TIKTOK_CLICKER_HCI",
			help="Bumble transport of the HCI controller, e.g. serial:COM3,1000000,rtscts.",
		),
	]
	initiator_keys: Annotated[
		InitiatorKeys,
		Parameter(help="Keys we offer to distribute when pairing; enc-id is the passthrough's."),
	] = InitiatorKeys.ENC_ID
	own_address: Annotated[str, Parameter(help="Static random address to connect from.")] = (
		"F0:F1:F2:F3:F4:F5"
	)
	out: Annotated[
		Path, Parameter(help="Directory to write the journal and its HCI btsnoop log to.")
	] = Path("captures")


def seconds_since(origin: float) -> float:
	return time.monotonic() - origin


@asynccontextmanager
async def capture_session(
	address: str, options: LinkOptions, banner: str
) -> AsyncGenerator[Session]:
	path = (
		options.out / f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}-{address.replace(':', '').lower()}.jsonl"
	)
	snoop = path.with_suffix(".btsnoop")
	terminal = Terminal()
	inbox = asyncio.Queue[DeviceEvent]()
	clock = partial(seconds_since, time.monotonic())
	terminal.say(f"{banner}\nJournal: {path}\nHCI snoop: {snoop}")
	with journal(path) as append:
		record = router(append, inbox, terminal)
		record(
			Started(
				t=clock(),
				utc=datetime.now(UTC).isoformat(),
				version=version("tiktok-clicker"),
				hci=options.hci,
				target=address,
				initiator_keys=options.initiator_keys,
			)
		)
		async with hci_device(
			options.hci, options.own_address, snoop, options.initiator_keys
		) as device:
			yield Session(
				device=device, target=address, steps=StepContext(record, inbox, clock, terminal)
			)
	terminal.say(f"\nDone. Journal: {path}")


@app.command
async def guided(
	address: Annotated[str, Parameter(help="The ring's BLE address, e.g. EB:80:03:88:70:8B.")],
	options: LinkOptions,
	*,
	modes: Annotated[tuple[Mode, ...], Parameter(help="Ring modes to walk through, in order.")] = (
		Mode.C,
		Mode.T,
	),
	buttons: Annotated[
		tuple[Button, ...], Parameter(help="Buttons to press in each mode, in order.")
	] = (Button.UP, Button.DOWN, Button.CENTER),
	presses: Annotated[int, Parameter(help="Presses per button.")] = 3,
	hold_seconds: Annotated[
		int | None, Parameter(help="Also hold each button for this many seconds.")
	] = None,
) -> None:
	"""Walk through each mode and button, journaling every HID report the ring sends."""
	async with capture_session(address, options, GUIDE) as session:
		await run_guided(session, guided_plan(modes, buttons, presses, hold_seconds))


@app.command
async def soak(
	address: Annotated[str, Parameter(help="The ring's BLE address, e.g. EB:80:03:88:70:8B.")],
	options: LinkOptions,
	*,
	seconds: Annotated[float, Parameter(help="How long to hold the idle link.")] = 45.0,
) -> None:
	"""Link once and hold the link idle, reporting whether the ring drops it."""
	async with capture_session(address, options, SOAK) as session:
		session.steps.console.say(describe_soak(await soak_link(session, seconds)))


@app.command
def show(
	path: Annotated[Path, Parameter(help="Journal written by `guided` or `soak`.")],
) -> None:
	"""Print a journal: each link's GATT table, then every step and the reports it produced."""
	print(render_journal(read_journal(path)))


def main() -> None:
	app()

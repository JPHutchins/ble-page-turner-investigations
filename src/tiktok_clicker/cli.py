"""Command line interface."""

import asyncio
import time
from datetime import UTC, datetime
from functools import partial
from importlib.metadata import version
from pathlib import Path
from typing import Annotated, Final

from cyclopts import App, Parameter

from tiktok_clicker.guided import Session, StepContext, Terminal, router, run_guided
from tiktok_clicker.journal import journal, read_journal
from tiktok_clicker.link import hci_device
from tiktok_clicker.model import Button, DeviceEvent, Mode, Started
from tiktok_clicker.plan import guided_plan
from tiktok_clicker.render import render_journal

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


def seconds_since(origin: float) -> float:
	return time.monotonic() - origin


@app.command
async def guided(
	address: Annotated[str, Parameter(help="The ring's BLE address, e.g. EB:80:03:88:70:8B.")],
	*,
	hci: Annotated[
		str,
		Parameter(
			env_var="TIKTOK_CLICKER_HCI",
			help="Bumble transport of the HCI controller, e.g. serial:COM3,1000000,rtscts.",
		),
	],
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
	own_address: Annotated[
		str, Parameter(help="Static random address to connect from.")
	] = "F0:F1:F2:F3:F4:F5",
	out: Annotated[Path, Parameter(help="Directory to write the journal to.")] = Path("captures"),
) -> None:
	"""Walk through each mode and button, journaling every HID report the ring sends."""
	path = out / f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}-{address.replace(':', '').lower()}.jsonl"
	terminal = Terminal()
	inbox = asyncio.Queue[DeviceEvent]()
	clock = partial(seconds_since, time.monotonic())
	terminal.say(f"{GUIDE}\nJournal: {path}")
	with journal(path) as append:
		record = router(append, inbox, terminal)
		record(
			Started(
				t=clock(),
				utc=datetime.now(UTC).isoformat(),
				version=version("tiktok-clicker"),
				hci=hci,
				target=address,
			)
		)
		async with hci_device(hci, own_address) as device:
			await run_guided(
				Session(
					device=device, target=address, steps=StepContext(record, inbox, clock, terminal)
				),
				guided_plan(modes, buttons, presses, hold_seconds),
			)
	terminal.say(f"\nDone. Journal: {path}")


@app.command
def show(
	path: Annotated[Path, Parameter(help="Journal written by `guided`.")],
) -> None:
	"""Print a journal: each link's GATT table, then every step and the reports it produced."""
	print(render_journal(read_journal(path)))


def main() -> None:
	app()

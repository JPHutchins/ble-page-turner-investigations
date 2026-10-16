"""Command line interface."""

import asyncio
import sys
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import partial
from importlib.metadata import version
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Final

from cyclopts import App, Parameter

from tiktok_clicker.guard import judge
from tiktok_clicker.guided import Session, StepContext, Terminal, router, run_guided
from tiktok_clicker.journal import journal, read_journal
from tiktok_clicker.kindle import (
	AuditEntry,
	Ran,
	Refused,
	Target,
	append_audit,
	described,
	execute,
	md5,
	md5_command,
	pull_command,
	pulled_entry,
	push_command,
	remote_md5,
	summary,
)
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


kindle: Final = App(
	name="kindle",
	help="Guarded commands on the Kindle under test, each journaled to an audit log.",
)
app.command(kindle)


@Parameter(name="*")
@dataclass(frozen=True, kw_only=True)
class KindleOptions:
	host: Annotated[
		str, Parameter(env_var="TIKTOK_CLICKER_KINDLE", help="The Kindle's address on the LAN.")
	]
	port: Annotated[int, Parameter(help="Its SSH port.")] = 2222
	user: Annotated[str, Parameter(help="SSH user.")] = "root"
	ssh: Annotated[Path, Parameter(env_var="TIKTOK_CLICKER_SSH", help="ssh client to run.")] = Path(
		"ssh"
	)
	audit: Annotated[Path, Parameter(help="Journal of every command, run or refused.")] = Path(
		"hil/audit.jsonl"
	)

	def target(self) -> Target:
		return Target(
			self.host, self.port, self.user, self.ssh, self.audit.with_name("known_hosts")
		)


def exit_code(entry: AuditEntry) -> int:
	match entry:
		case Ran(exit_code=0):
			return 0
		case Ran() | Refused():
			return 1


def show_output(entry: AuditEntry) -> None:
	match entry:
		case Ran(stdout=out, stderr=err):
			print(out, end="")
			print(err, end="", file=sys.stderr)
		case Refused():
			pass


@kindle.command(name="run")
def kindle_run(
	command: Annotated[str, Parameter(help="Shell command to run on the device.")],
	options: KindleOptions,
	*,
	write: Annotated[
		bool, Parameter(help="Allow a command that changes the device, once reviewed.")
	] = False,
	dry_run: Annotated[bool, Parameter(help="Only print the guard's verdict.")] = False,
	timeout: Annotated[float, Parameter(help="Seconds before the command is cut off.")] = 30.0,
) -> int:
	"""Run one command on the device if the guard allows it."""
	if dry_run:
		print(judge(command, write=write))
		return 0
	entry, _ = execute(options.target(), command, write=write, timeout=timeout)
	append_audit(options.audit, entry)
	show_output(entry)
	print(summary(entry))
	return exit_code(entry)


@kindle.command
def push(
	local: Annotated[Path, Parameter(help="File to copy to the device.")],
	remote: Annotated[str, Parameter(help="Absolute path to write it to on the device.")],
	options: KindleOptions,
	*,
	write: Annotated[bool, Parameter(help="Acknowledge that this writes to the device.")] = False,
) -> int:
	"""Copy a file to the device, then compare its md5 there with ours."""
	data = local.read_bytes()
	entry, _ = execute(options.target(), push_command(remote), write=write, timeout=300, stdin=data)
	append_audit(options.audit, entry)
	print(summary(entry))
	if exit_code(entry):
		return 1
	check, _ = execute(options.target(), md5_command(remote), write=False, timeout=60)
	append_audit(options.audit, check)
	matched = remote_md5(check) == md5(data)
	print(f"local {described(data)}, device md5 {remote_md5(check)}")
	print("MATCH" if matched else "MISMATCH")
	return 0 if matched else 1


@kindle.command
def pull(
	remote: Annotated[str, Parameter(help="Absolute path of the file on the device.")],
	local: Annotated[Path, Parameter(help="Where to save it here.")],
	options: KindleOptions,
) -> int:
	"""Copy a file from the device."""
	entry, data = execute(options.target(), pull_command(remote), write=False, timeout=300)
	recorded = pulled_entry(entry, data)
	append_audit(options.audit, recorded)
	print(summary(recorded))
	if exit_code(recorded):
		return 1
	local.parent.mkdir(parents=True, exist_ok=True)
	local.write_bytes(data)
	print(f"{local}: {described(data)}")
	return 0


def main() -> None:
	app()

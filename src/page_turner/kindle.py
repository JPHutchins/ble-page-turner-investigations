"""Run judged commands on the Kindle under test over SSH, journaling every one."""

import hashlib
import shlex
import subprocess
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final, NamedTuple

import msgspec

from page_turner.guard import Access, Denied, judge

if TYPE_CHECKING:
	from pathlib import Path


class Target(NamedTuple):
	host: str
	port: int
	user: str
	ssh: Path
	known_hosts: Path


class Ran(msgspec.Struct, frozen=True, kw_only=True, tag="ran", tag_field="kind"):
	utc: str
	command: str
	access: Access
	exit_code: int | None
	seconds: float
	stdout: str
	stderr: str


class Refused(msgspec.Struct, frozen=True, kw_only=True, tag="refused", tag_field="kind"):
	utc: str
	command: str
	reason: str


type AuditEntry = Ran | Refused

CONNECT_SECONDS: Final = 8


def ssh_argv(target: Target, command: str) -> list[str]:
	r"""The ssh invocation for one remote command, never prompting.

	>>> from pathlib import PurePosixPath
	>>> ssh_argv(Target("k", 2222, "root", PurePosixPath("ssh"), PurePosixPath("kh")), "true")[-2:]
	['root@k', 'true']
	"""
	options = (
		"BatchMode=yes",
		f"ConnectTimeout={CONNECT_SECONDS}",
		"ServerAliveInterval=5",
		"ServerAliveCountMax=2",
		"StrictHostKeyChecking=accept-new",
		f"UserKnownHostsFile={target.known_hosts}",
		"LogLevel=ERROR",
	)
	return [
		str(target.ssh),
		"-p",
		str(target.port),
		*(word for option in options for word in ("-o", option)),
		f"{target.user}@{target.host}",
		command,
	]


def text(data: bytes) -> str:
	return data.decode("utf-8", errors="replace")


def md5(data: bytes) -> str:
	return hashlib.md5(data).hexdigest()


def described(data: bytes) -> str:
	return f"<{len(data)} bytes, md5 {md5(data)}>"


def execute(
	target: Target, command: str, *, write: bool, timeout: float, stdin: bytes | None = None
) -> tuple[AuditEntry, bytes]:
	utc = datetime.now(UTC).isoformat()
	match judge(command, write=write):
		case Denied(reason):
			return Refused(utc=utc, command=command, reason=reason), b""
		case allowed:
			started = time.monotonic()
			try:
				done = subprocess.run(
					ssh_argv(target, command),
					input=stdin,
					capture_output=True,
					timeout=timeout,
					check=False,
				)
				exit_code, out, err = done.returncode, done.stdout, done.stderr
			except subprocess.TimeoutExpired as expired:
				exit_code, out, err = None, expired.stdout or b"", expired.stderr or b""
			return Ran(
				utc=utc,
				command=command,
				access=allowed.access,
				exit_code=exit_code,
				seconds=round(time.monotonic() - started, 3),
				stdout=text(out) if stdin is None else "",
				stderr=text(err),
			), out


def push_command(remote: str) -> str:
	return f"cat > {shlex.quote(remote)}"


def pull_command(remote: str) -> str:
	return f"cat {shlex.quote(remote)}"


def md5_command(remote: str) -> str:
	return f"md5sum {shlex.quote(remote)}"


def remote_md5(entry: AuditEntry) -> str | None:
	match entry:
		case Ran(exit_code=0, stdout=stdout) if stdout.split():
			return stdout.split()[0]
		case _:
			return None


def append_audit(path: Path, entry: AuditEntry) -> None:
	path.parent.mkdir(parents=True, exist_ok=True)
	with path.open("ab") as stream:
		stream.write(msgspec.json.encode(entry) + b"\n")


def summary(entry: AuditEntry) -> str:
	match entry:
		case Refused(reason=reason):
			return f"REFUSED: {reason}"
		case Ran(exit_code=None, seconds=seconds, access=access):
			return f"[timed out after {seconds} s, {access}]"
		case Ran(exit_code=code, seconds=seconds, access=access):
			return f"[exit {code}, {seconds} s, {access}]"


def pulled_entry(entry: AuditEntry, data: bytes) -> AuditEntry:
	match entry:
		case Ran():
			return msgspec.structs.replace(entry, stdout=described(data))
		case Refused():
			return entry

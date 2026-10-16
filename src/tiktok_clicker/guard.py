"""Judge a shell command for the Kindle under test before it is sent."""

import re
import shlex
from enum import StrEnum
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Final, NamedTuple
from urllib.parse import urlsplit

if TYPE_CHECKING:
	from collections.abc import Iterator, Sequence


class Access(StrEnum):
	READ = "read"
	WRITE = "write"


class Allowed(NamedTuple):
	access: Access


class Denied(NamedTuple):
	reason: str


type Verdict = Allowed | Denied


class Simple(NamedTuple):
	program: str
	args: tuple[str, ...]
	writes_to: tuple[str, ...]


INSTALL: Final = PurePosixPath("/mnt/us/kindle-button-mapper")
SCRATCH: Final = (PurePosixPath("/mnt/us/kbm-hil"), PurePosixPath("/tmp/kbm-hil"))
APP_CACHE: Final = PurePosixPath("/var/local/mesquite/com.lzampier.mappermanager")
WRITABLE: Final = (INSTALL, *SCRATCH, APP_CACHE)
REMOVABLE_TREES: Final = (*SCRATCH, APP_CACHE)

NEVER: Final = {
	program: reason
	for reason, programs in (
		("remounts or changes filesystems", ("mntroot", "mount", "umount", "mkfs", "fdisk")),
		("writes raw storage or boot settings", ("dd", "flash_erase", "nandwrite", "fw_setenv")),
		("changes power state", ("reboot", "shutdown", "halt", "poweroff")),
		("edits system databases", ("sqlite3",)),
		("changes the kernel", ("insmod", "rmmod", "modprobe")),
		("kills by name", ("killall", "pkill")),
		("drives the system UI; do that on the device", ("lipc-set-prop",)),
		(
			"runs code the guard cannot read",
			(
				*("sh", "ash", "bash", "busybox", "eval", "exec", "xargs", "source", "."),
				*("nohup", "env", "su", "sudo", "chroot", "awk", "sed", "perl", "python"),
				*("python3", "lua", "tee", "curl"),
			),
		),
	)
	for program in programs
}
READERS: Final = frozenset(
	{
		*("cat", "ls", "grep", "head", "tail", "df", "du", "ps", "uname", "md5sum", "sha256sum"),
		*("stat", "wc", "hexdump", "od", "date", "uptime", "free", "find", "readlink", "dmesg"),
		*("which", "echo", "test", "true", "sleep", "sort", "uniq", "cut", "tr", "strings"),
		*("basename", "dirname", "pwd", "id", "pidof", "lipc-get-prop", "evtest"),
	}
)
WRITERS: Final = frozenset({"cp", "mv", "mkdir", "chmod", "rm", "touch"})
FIND_ACTIONS: Final = frozenset({"-delete", "-exec", "-execdir", "-ok", "-okdir", "-fprint"})
HELPER: Final = "http://127.0.0.1:8322"
HELPER_READS: Final = frozenset({"/status", "/devices", "/resolve", "/actions", "/logs", "/config"})
OUR_JOB: Final = "kindle-button-mapper"

CONTROL: Final = frozenset({";", "&&", "||", "|"})
REDIRECTS: Final = frozenset({">", ">>", ">|", "&>", "&>>"})
REFERENCES: Final = frozenset({"<", ">&", "<&"})
PUNCTUATION: Final = frozenset("();<>|&")
SIGNAL_OR_PID: Final = re.compile(r"-(?:[A-Z]+|\d+)|\d+")
WRITE_FLAG: Final = "changes the device: review it, then rerun with --write"


def judge(command: str, *, write: bool) -> Verdict:
	"""Whether a command may run, and whether it changes the device.

	>>> judge("cat /proc/bus/input/devices", write=False)
	Allowed(access=<Access.READ: 'read'>)
	>>> judge("/usr/sbin/mntroot rw", write=True)
	Denied(reason='mntroot: remounts or changes filesystems')
	>>> judge("cp -p /mnt/us/kindle-button-mapper/config.ini /mnt/us/kbm-hil/", write=False)
	Denied(reason='changes the device: review it, then rerun with --write')
	"""
	if "$(" in command or "`" in command:
		return Denied("command substitution hides what runs")
	try:
		words = tokens(command)
	except ValueError as error:
		return Denied(f"cannot parse: {error}")
	if not words:
		return Denied("empty command")
	verdicts = tuple(
		part if isinstance(part, Denied) else judge_simple(part) for part in simple_commands(words)
	)
	match next((verdict for verdict in verdicts if isinstance(verdict, Denied)), None):
		case Denied() as denied:
			return denied
		case None if any(verdict == Allowed(Access.WRITE) for verdict in verdicts):
			return Allowed(Access.WRITE) if write else Denied(WRITE_FLAG)
		case None:
			return Allowed(Access.READ)


def tokens(command: str) -> list[str]:
	lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
	lexer.whitespace_split = True
	return list(lexer)


def simple_commands(words: Sequence[str]) -> Iterator[Simple | Denied]:
	current: list[str] = []
	targets: list[str] = []
	pending: str | None = None
	for word in (*words, ";"):
		if pending is not None:
			targets.extend((word,) if pending in REDIRECTS else ())
			pending = None
		elif word in CONTROL:
			if current:
				yield Simple(current[0], tuple(current[1:]), tuple(targets))
			elif word != ";":
				yield Denied(f"{word!r} without a command before it")
			current, targets = [], []
		elif word in REDIRECTS | REFERENCES:
			if current[1:] and current[-1].isdigit():
				current.pop()
			pending = word
		elif set(word) <= PUNCTUATION:
			yield Denied(f"{word!r}: no subshells or background jobs")
		else:
			current.append(word)
	if pending is not None:
		yield Denied(f"{pending!r} without a target")


def judge_simple(simple: Simple) -> Verdict:
	redirected = tuple(target for target in simple.writes_to if target != "/dev/null")
	if not all(inside(target, WRITABLE) for target in redirected):
		return Denied(f"redirects outside {', '.join(map(str, WRITABLE))}")
	verdict = judge_program(PurePosixPath(simple.program), simple.args)
	return Allowed(Access.WRITE) if verdict == Allowed(Access.READ) and redirected else verdict


def judge_program(program: PurePosixPath, args: tuple[str, ...]) -> Verdict:
	name = program.name
	match name:
		case _ if name in NEVER:
			return Denied(f"{name}: {NEVER[name]}")
		case "timeout" if args[1:]:
			return judge_program(PurePosixPath(args[1]), args[2:])
		case "kindle-button-mapper" if args == ("--version",) and program.parent in {
			INSTALL,
			PurePosixPath(),
		}:
			return Allowed(Access.READ)
		case "initctl":
			return judge_initctl(args)
		case "kill" if args and all(SIGNAL_OR_PID.fullmatch(arg) for arg in args):
			return Allowed(Access.WRITE)
		case "wget":
			return judge_wget(args)
		case "find" if FIND_ACTIONS & set(args):
			return Denied("find: no actions, only listing")
		case _ if name in WRITERS:
			return judge_writer(name, args)
		case _ if name in READERS:
			return Allowed(Access.READ)
		case _:
			return Denied(f"{name}: not on the guard's list")


def judge_initctl(args: tuple[str, ...]) -> Verdict:
	match args:
		case ("status" | "list", *_):
			return Allowed(Access.READ)
		case ("start" | "stop" | "restart", job) if job == OUR_JOB:
			return Allowed(Access.WRITE)
		case _:
			return Denied(f"initctl: only status/list, or start/stop/restart of {OUR_JOB}")


def judge_wget(args: tuple[str, ...]) -> Verdict:
	urls = tuple(arg for arg in args if not arg.startswith("-"))
	options = {arg for arg in args if arg.startswith("-")}
	match urls:
		case (url,) if (
			options in ({"-qO-"}, {"-q", "-O-"}, {"-O-"})
			and url.startswith(f"{HELPER}/")
			and urlsplit(url).path in HELPER_READS
		):
			return Allowed(Access.READ)
		case _:
			reads = ", ".join(sorted(HELPER_READS))
			return Denied(f"wget: only -qO- from the mapper's helper ({reads})")


def judge_writer(name: str, args: tuple[str, ...]) -> Verdict:
	options = tuple(arg for arg in args if arg.startswith("-"))
	operands = tuple(arg for arg in args if not arg.startswith("-"))
	paths = operands[1:] if name == "chmod" else operands
	recursive = any("r" in option.lower() for option in options if not option.startswith("--"))
	match name:
		case _ if not paths:
			return Denied(f"{name}: nothing to act on")
		case _ if not all(PurePosixPath(path).is_absolute() for path in paths):
			return Denied(f"{name}: use absolute paths")
		case "rm" | "mv" if any(PurePosixPath(path) == INSTALL for path in paths):
			return Denied(f"{name}: never the whole install")
		case "rm" if recursive and not all(inside(path, REMOVABLE_TREES) for path in paths):
			return Denied(f"rm -r: only under {', '.join(map(str, REMOVABLE_TREES))}")
		case "cp" if not inside(paths[-1], WRITABLE):
			return Denied(f"cp: only into {', '.join(map(str, WRITABLE))}")
		case "cp":
			return Allowed(Access.WRITE)
		case _ if not all(inside(path, WRITABLE) for path in paths):
			return Denied(f"{name}: only under {', '.join(map(str, WRITABLE))}")
		case _:
			return Allowed(Access.WRITE)


def inside(path: str, roots: Sequence[PurePosixPath]) -> bool:
	candidate = PurePosixPath(path)
	return (
		candidate.is_absolute()
		and ".." not in candidate.parts
		and any(candidate == root or root in candidate.parents for root in roots)
	)

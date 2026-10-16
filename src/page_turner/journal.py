"""Append-only JSON Lines journal of `Entry` records, flushed per line so a crash loses nothing."""

from contextlib import contextmanager
from typing import TYPE_CHECKING, Final

import msgspec

from page_turner.model import Entry

if TYPE_CHECKING:
	from collections.abc import Callable, Generator
	from pathlib import Path

_decoder: Final = msgspec.json.Decoder[Entry](Entry)


def decode_entries(lines: bytes) -> tuple[Entry, ...]:
	r"""Decode a journal's bytes, skipping blank lines.

	>>> from page_turner.model import Disconnected
	>>> decode_entries(b'{"kind":"disconnected","t":1.5,"reason":19}\n\n')
	(Disconnected(t=1.5, reason=19),)
	"""
	return tuple(_decoder.decode(line) for line in lines.splitlines() if line.strip())


def encode_entry(entry: Entry) -> bytes:
	r"""Encode one journal line.

	>>> from page_turner.model import Disconnected
	>>> encode_entry(Disconnected(t=1.5, reason=19))
	b'{"kind":"disconnected","t":1.5,"reason":19}\n'
	"""
	return msgspec.json.encode(entry) + b"\n"


def read_journal(path: Path) -> tuple[Entry, ...]:
	return decode_entries(path.read_bytes())


@contextmanager
def journal(path: Path) -> Generator[Callable[[Entry], None]]:
	path.parent.mkdir(parents=True, exist_ok=True)
	with path.open("ab") as stream:

		def append(entry: Entry) -> None:
			stream.write(encode_entry(entry))
			stream.flush()

		yield append

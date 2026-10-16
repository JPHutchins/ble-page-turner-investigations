import asyncio
from collections.abc import Iterator
from typing import Final

from page_turner.guided import StepContext, router, run_steps
from page_turner.model import (
	Button,
	DeviceEvent,
	Disconnected,
	Entry,
	Mode,
	Press,
	Report,
	Started,
	Step,
	StepBegan,
	StepEnded,
	SwitchMode,
	Verdict,
)

SWITCH: Final = SwitchMode(mode=Mode.C)
PRESS_UP: Final = Press(mode=Mode.C, button=Button.UP, count=3)
PRESS_DOWN: Final = Press(mode=Mode.C, button=Button.DOWN, count=3)
TAP: Final = Report(t=0.0, handle=0x1B, report_id=4, hex="07")
DROPPED: Final = Disconnected(t=0.0, reason=0x13)

type Script = Iterator[tuple[str, tuple[DeviceEvent, ...]]]


class ScriptedConsole:
	"""Answers prompts in order; each answer first delivers what the ring "sent" meanwhile."""

	def __init__(self, inbox: asyncio.Queue[DeviceEvent], script: Script) -> None:
		self.inbox = inbox
		self.script = script
		self.said: list[str] = []

	async def ask(self, prompt: str) -> str:
		answer, events = next(self.script)
		for event in events:
			self.inbox.put_nowait(event)
		return answer

	def say(self, text: str) -> None:
		self.said.append(text)


def scripted(
	*script: tuple[str, tuple[DeviceEvent, ...]],
) -> tuple[StepContext, list[Entry], ScriptedConsole]:
	inbox = asyncio.Queue[DeviceEvent]()
	journaled: list[Entry] = []
	console = ScriptedConsole(inbox, iter(script))
	return StepContext(journaled.append, inbox, lambda: 0.0, console), journaled, console


def verdicts(journaled: list[Entry]) -> list[tuple[Step, Verdict]]:
	return [(entry.step, entry.verdict) for entry in journaled if isinstance(entry, StepEnded)]


async def test_kept_steps_run_to_completion() -> None:
	context, journaled, console = scripted(("", ()), ("", ()), ("", (TAP, TAP)), ("", ()))
	assert await run_steps(context, (SWITCH, PRESS_UP)) == ()
	assert verdicts(journaled) == [(SWITCH, Verdict.KEEP), (PRESS_UP, Verdict.KEEP)]
	assert "    2 reports (id 4 x2)" in console.said


async def test_redo_repeats_the_step() -> None:
	context, journaled, _ = scripted(("", ()), ("r", ()), ("", (TAP,)), ("", ()))
	assert await run_steps(context, (PRESS_UP,)) == ()
	assert verdicts(journaled) == [(PRESS_UP, Verdict.REDO), (PRESS_UP, Verdict.KEEP)]


async def test_quit_drops_the_rest() -> None:
	context, journaled, _ = scripted(("", ()), ("q", ()))
	assert await run_steps(context, (PRESS_UP, PRESS_DOWN)) == ()
	assert verdicts(journaled) == [(PRESS_UP, Verdict.QUIT)]


async def test_drop_during_a_step_hands_back_what_is_left() -> None:
	context, _, _ = scripted(("", (TAP, DROPPED)), ("", ()))
	assert await run_steps(context, (SWITCH, PRESS_UP)) == (PRESS_UP,)


async def test_empty_press_defaults_to_redo() -> None:
	context, journaled, _ = scripted(("", ()), ("", ()), ("", (TAP,)), ("", ()))
	assert await run_steps(context, (PRESS_UP,)) == ()
	assert verdicts(journaled) == [(PRESS_UP, Verdict.REDO), (PRESS_UP, Verdict.KEEP)]


async def test_empty_press_can_still_be_kept() -> None:
	context, journaled, _ = scripted(("", ()), ("k", ()))
	assert await run_steps(context, (PRESS_UP,)) == ()
	assert verdicts(journaled) == [(PRESS_UP, Verdict.KEEP)]


async def test_press_lost_to_a_drop_is_redone_on_the_next_link() -> None:
	"""The first capture lost C-mode DOWN: the link dropped mid-step and Enter kept the empty step."""
	context, _, _ = scripted(("", (DROPPED,)), ("", ()))
	assert await run_steps(context, (PRESS_UP, PRESS_DOWN)) == (PRESS_UP, PRESS_DOWN)


async def test_drop_between_steps_relinks_before_prompting() -> None:
	context, journaled, _ = scripted(("", (TAP,)), ("", (DROPPED,)))
	assert await run_steps(context, (PRESS_UP, PRESS_DOWN)) == (PRESS_DOWN,)
	assert not any(isinstance(entry, StepBegan) and entry.step == PRESS_DOWN for entry in journaled)


def test_router_queues_and_echoes_only_device_events() -> None:
	inbox = asyncio.Queue[DeviceEvent]()
	journaled: list[Entry] = []
	console = ScriptedConsole(inbox, iter(()))
	route = router(journaled.append, inbox, console)
	started = Started(t=0.0, utc="", version="", hci="", target="")
	route(started)
	route(TAP)
	assert journaled == [started, TAP]
	assert inbox.get_nowait() == TAP
	assert inbox.empty()
	assert len(console.said) == 1

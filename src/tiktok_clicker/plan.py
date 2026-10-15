"""The guided capture's step plan and the words shown for each step."""

from typing import TYPE_CHECKING, NamedTuple

from tiktok_clicker.model import Button, Hold, Mode, Press, Step, SwitchMode, Verdict

if TYPE_CHECKING:
	from collections.abc import Iterable, Sequence


def guided_plan(
	modes: Iterable[Mode], buttons: Sequence[Button], presses: int, hold_seconds: int | None
) -> tuple[Step, ...]:
	"""Every mode switch is followed by that mode's presses, then its holds when requested.

	>>> [type(step).__name__ for step in guided_plan((Mode.C,), (Button.UP, Button.DOWN), 3, None)]
	['SwitchMode', 'Press', 'Press']
	>>> guided_plan((Mode.T,), (Button.CENTER,), 2, 3)
	(SwitchMode(mode=<Mode.T: 'T'>), Press(mode=<Mode.T: 'T'>, button=<Button.CENTER: 'center'>, count=2), Hold(mode=<Mode.T: 'T'>, button=<Button.CENTER: 'center'>, seconds=3))
	"""
	return tuple(
		step
		for mode in modes
		for step in (
			SwitchMode(mode=mode),
			*(Press(mode=mode, button=button, count=presses) for button in buttons),
			*(
				()
				if hold_seconds is None
				else (Hold(mode=mode, button=button, seconds=hold_seconds) for button in buttons)
			),
		)
	)


def instruction(step: Step) -> str:
	"""What the person holding the ring is asked to do.

	>>> instruction(SwitchMode(mode=Mode.T))
	'Put the ring in T mode.'
	>>> instruction(Press(mode=Mode.C, button=Button.UP, count=3))
	'[C mode] Press UP 3 times, about 1 second apart.'
	>>> instruction(Hold(mode=Mode.C, button=Button.DOWN, seconds=2))
	'[C mode] Hold DOWN for about 2 seconds, then release.'
	"""
	match step:
		case SwitchMode(mode=mode):
			return f"Put the ring in {mode} mode."
		case Press(mode=mode, button=button, count=count):
			return f"[{mode} mode] Press {button.upper()} {count} times, about 1 second apart."
		case Hold(mode=mode, button=button, seconds=seconds):
			return f"[{mode} mode] Hold {button.upper()} for about {seconds} seconds, then release."


class Answer(NamedTuple):
	verdict: Verdict
	note: str


def parse_answer(text: str) -> Answer:
	"""Blank keeps the step, `r` redoes it, `q` quits, and anything else is kept as a note.

	>>> parse_answer("")
	Answer(verdict=<Verdict.KEEP: 'keep'>, note='')
	>>> parse_answer(" R ")
	Answer(verdict=<Verdict.REDO: 'redo'>, note='')
	>>> parse_answer("q")
	Answer(verdict=<Verdict.QUIT: 'quit'>, note='')
	>>> parse_answer("LED blinked twice")
	Answer(verdict=<Verdict.KEEP: 'keep'>, note='LED blinked twice')
	"""
	match text.strip().lower():
		case "r":
			return Answer(Verdict.REDO, "")
		case "q":
			return Answer(Verdict.QUIT, "")
		case _:
			return Answer(Verdict.KEEP, text.strip())

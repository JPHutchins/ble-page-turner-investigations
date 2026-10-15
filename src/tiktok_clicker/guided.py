"""The guided capture: prompt for each step, collect what the ring sent, relink when it drops."""

import asyncio
from typing import TYPE_CHECKING, NamedTuple, Protocol

from tiktok_clicker.link import (
	ADVERTISEMENT_TIMEOUT_SECONDS,
	Clock,
	Linked,
	LinkFailure,
	Record,
	ring_link,
)
from tiktok_clicker.model import (
	Connected,
	DeviceEvent,
	Disconnected,
	Entry,
	Indication,
	LinkFailed,
	Report,
	Started,
	Step,
	StepBegan,
	StepEnded,
	Verdict,
)
from tiktok_clicker.plan import Answer, instruction, parse_answer
from tiktok_clicker.render import describe, summarize

if TYPE_CHECKING:
	from bumble.device import Device


class Console(Protocol):
	async def ask(self, prompt: str) -> str: ...

	def say(self, text: str) -> None: ...


class Terminal:
	async def ask(self, prompt: str) -> str:
		return await asyncio.to_thread(input, prompt)

	def say(self, text: str) -> None:
		print(text, flush=True)


class StepContext(NamedTuple):
	record: Record
	inbox: asyncio.Queue[DeviceEvent]
	clock: Clock
	console: Console


class Session(NamedTuple):
	device: Device
	target: str
	steps: StepContext


class StepResult(NamedTuple):
	answer: Answer
	events: tuple[DeviceEvent, ...]


def drain[T](queue: asyncio.Queue[T]) -> tuple[T, ...]:
	return tuple(queue.get_nowait() for _ in range(queue.qsize()))


def link_lost(events: tuple[DeviceEvent, ...]) -> bool:
	return any(isinstance(event, Disconnected) for event in events)


def remaining_after(steps: tuple[Step, ...], verdict: Verdict) -> tuple[Step, ...]:
	match verdict:
		case Verdict.KEEP:
			return steps[1:]
		case Verdict.REDO:
			return steps
		case Verdict.QUIT:
			return ()


def router(append: Record, inbox: asyncio.Queue[DeviceEvent], console: Console) -> Record:
	"""Journal every entry; also queue and echo what the ring sends, so a step can summarize it."""

	def route(entry: Entry) -> None:
		append(entry)
		match entry:
			case Report() | Indication() | Disconnected():
				inbox.put_nowait(entry)
				console.say(describe(entry))
			case Connected() | LinkFailed():
				console.say(describe(entry))
			case Started() | StepBegan() | StepEnded():
				pass

	return route


async def perform(context: StepContext, step: Step) -> StepResult:
	context.record(StepBegan(t=context.clock(), step=step))
	await context.console.ask(f"\n>>> {instruction(step)}\n    Press Enter when done. ")
	events = drain(context.inbox)
	context.console.say(f"    {summarize(events)}")
	answer = parse_answer(
		await context.console.ask("    Enter = keep, r = redo, q = quit, or type a note: ")
	)
	context.record(
		StepEnded(t=context.clock(), step=step, verdict=answer.verdict, note=answer.note)
	)
	return StepResult(answer=answer, events=events)


async def run_steps(context: StepContext, steps: tuple[Step, ...]) -> tuple[Step, ...]:
	"""Run steps until done or the link drops; the steps still to run are returned."""
	if not steps or link_lost(drain(context.inbox)):
		return steps
	result = await perform(context, steps[0])
	remaining = remaining_after(steps, result.answer.verdict)
	return remaining if link_lost(result.events) else await run_steps(context, remaining)


async def attempt(session: Session, steps: tuple[Step, ...]) -> tuple[Step, ...] | LinkFailure:
	async with ring_link(
		session.device, session.target, session.steps.record, session.steps.clock
	) as link:
		match link:
			case Linked():
				return await run_steps(session.steps, steps)
			case LinkFailure():
				return link


async def run_guided(session: Session, steps: tuple[Step, ...]) -> None:
	if not steps:
		return
	console = session.steps.console
	console.say(
		f"\nWaiting up to {ADVERTISEMENT_TIMEOUT_SECONDS:.0f} s for the ring to advertise."
		" If it is asleep, press any ring button to wake it."
	)
	match await attempt(session, steps):
		case LinkFailure(error=error):
			session.steps.record(LinkFailed(t=session.steps.clock(), error=error))
			answer = parse_answer(
				await console.ask("Wake the ring, then press Enter to retry, or q to quit: ")
			)
			await run_guided(session, () if answer.verdict is Verdict.QUIT else steps)
		case tuple() as remaining:
			await run_guided(session, remaining)

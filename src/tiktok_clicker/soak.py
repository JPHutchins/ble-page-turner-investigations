"""Hold one idle link to see whether, and when, the ring drops it."""

import asyncio
from typing import TYPE_CHECKING, NamedTuple

from tiktok_clicker.link import Linked, LinkFailure, ring_link
from tiktok_clicker.model import DeviceEvent, Disconnected

if TYPE_CHECKING:
	from tiktok_clicker.guided import Session, StepContext


class Held(NamedTuple):
	seconds: float


class Dropped(NamedTuple):
	after_seconds: float
	reason: int


type SoakOutcome = Held | Dropped | LinkFailure


async def next_disconnection(inbox: asyncio.Queue[DeviceEvent]) -> Disconnected:
	while not isinstance(event := await inbox.get(), Disconnected):
		pass
	return event


async def hold(context: StepContext, seconds: float) -> Held | Dropped:
	linked_at = context.clock()
	try:
		async with asyncio.timeout(seconds):
			disconnection = await next_disconnection(context.inbox)
	except TimeoutError:
		return Held(seconds=seconds)
	return Dropped(after_seconds=disconnection.t - linked_at, reason=disconnection.reason)


async def soak_link(session: Session, seconds: float) -> SoakOutcome:
	async with ring_link(
		session.device, session.target, session.steps.record, session.steps.clock
	) as link:
		match link:
			case Linked():
				return await hold(session.steps, seconds)
			case LinkFailure():
				return link


def describe_soak(outcome: SoakOutcome) -> str:
	match outcome:
		case Held(seconds=seconds):
			return f"Held the link for {seconds:.0f} s."
		case Dropped(after_seconds=after_seconds, reason=reason):
			return f"The ring dropped the link {after_seconds:.1f} s after linking (reason 0x{reason:02x})."
		case LinkFailure(error=error):
			return f"Could not link: {error}"

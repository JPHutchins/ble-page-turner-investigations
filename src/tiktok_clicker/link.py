"""The Bumble side: an HCI-attached device, and a paired, subscribed link to the ring."""

import asyncio
from collections.abc import Callable
from contextlib import AsyncExitStack, asynccontextmanager, closing
from typing import TYPE_CHECKING, Final, NamedTuple

from bumble.att import ATT_Error
from bumble.core import BaseBumbleError
from bumble.device import Connection, Device, Peer
from bumble.gatt import (
	GATT_HID_CONTROL_POINT_CHARACTERISTIC,
	GATT_PROTOCOL_MODE_CHARACTERISTIC,
	GATT_REPORT_REFERENCE_DESCRIPTOR,
	GATT_SERVICE_CHANGED_CHARACTERISTIC,
	Characteristic,
)
from bumble.hci import Address
from bumble.keys import MemoryKeyStore
from bumble.pairing import PairingConfig, PairingDelegate
from bumble.snoop import create_snooper
from bumble.transport import open_transport
from bumble.transport.common import SnoopingTransport
from bumble.utils import EventWatcher

from tiktok_clicker.gatt import boot_protocol_handles, input_report_ids, uuid_text
from tiktok_clicker.model import (
	Connected,
	Disconnected,
	Entry,
	GattCharacteristic,
	GattDescriptor,
	GattService,
	Indication,
	InitiatorKeys,
	NotRead,
	Read,
	ReadFailed,
	Report,
	Value,
)

if TYPE_CHECKING:
	from collections.abc import AsyncGenerator
	from pathlib import PurePath

	from bumble.device import Advertisement
	from bumble.gatt_client import AttributeProxy, CharacteristicProxy, DescriptorProxy

type Clock = Callable[[], float]
type Record = Callable[[Entry], None]

ADVERTISEMENT_TIMEOUT_SECONDS: Final = 30.0
CONNECT_TIMEOUT_SECONDS: Final = 15.0
EXIT_SUSPEND: Final = b"\x01"
REPORT_PROTOCOL: Final = b"\x01"


class PassthroughPairingDelegate(PairingDelegate):
	"""Pairs the way kindle-hid-passthrough's `AutoAcceptPairingDelegate` does."""

	def __init__(self, initiator_keys: PairingDelegate.KeyDistribution) -> None:
		super().__init__(
			io_capability=PairingDelegate.DISPLAY_OUTPUT_AND_YES_NO_INPUT,
			local_initiator_key_distribution=initiator_keys,
		)

	async def accept(self) -> bool:
		return True

	async def compare_numbers(self, number: int, digits: int) -> bool:
		return True

	async def get_number(self) -> int | None:
		return 0

	async def display_number(self, number: int, digits: int) -> None:
		return None


def key_distribution(keys: InitiatorKeys) -> PairingDelegate.KeyDistribution:
	"""`ENC_ID` is Bumble's default, and so kindle-hid-passthrough's.

	>>> key_distribution(InitiatorKeys.ENC_ID) == PairingDelegate.DEFAULT_KEY_DISTRIBUTION
	True
	"""
	match keys:
		case InitiatorKeys.ENC_ID:
			return (
				PairingDelegate.KeyDistribution.DISTRIBUTE_ENCRYPTION_KEY
				| PairingDelegate.KeyDistribution.DISTRIBUTE_IDENTITY_KEY
			)
		case InitiatorKeys.ID:
			return PairingDelegate.KeyDistribution.DISTRIBUTE_IDENTITY_KEY


def passthrough_pairing(keys: InitiatorKeys) -> Callable[[Connection], PairingConfig]:
	return lambda _connection: PairingConfig(
		sc=True,
		mitm=True,
		bonding=True,
		delegate=PassthroughPairingDelegate(key_distribution(keys)),
	)


def passthrough_irk(identity: Address) -> bytes:
	"""kindle-hid-passthrough's transport.py derivation, from our identity address instead of the
	controller's public one, which a Zephyr hci_uart reports as all zeros.

	>>> passthrough_irk(Address("F0:F1:F2:F3:F4:F5")).hex()
	'f5f4f3f2f1f0f5f4f3f2f1f0f5f4f3f2'
	"""
	return (bytes(identity) * 3)[:16]


def btsnoop_spec(path: PurePath) -> str:
	"""Bumble `str.format`s the file name, so literal braces are escaped.

	>>> from pathlib import PurePosixPath
	>>> btsnoop_spec(PurePosixPath("captures/{x}.btsnoop"))
	'btsnoop:file:captures/{{x}}.btsnoop'
	"""
	return f"btsnoop:file:{str(path).replace('{', '{{').replace('}', '}}')}"


@asynccontextmanager
async def hci_device(
	spec: str, own_address: str, snoop: PurePath, initiator_keys: InitiatorKeys
) -> AsyncGenerator[Device]:
	async with SnoopingTransport.create_with(
		await open_transport(spec), create_snooper(btsnoop_spec(snoop))
	) as hci:
		device = Device.with_hci("tiktok-clicker", Address(own_address), hci.source, hci.sink)
		device.keystore = MemoryKeyStore()
		device.pairing_config_factory = passthrough_pairing(initiator_keys)
		await device.power_on()
		device.irk = passthrough_irk(Address(own_address))
		yield device


@asynccontextmanager
async def scanning(device: Device) -> AsyncGenerator[None]:
	await device.start_scanning(filter_duplicates=True)
	try:
		yield
	finally:
		await device.stop_scanning()


def resolve_when_seen(
	seen: asyncio.Future[None], target: Address
) -> Callable[[Advertisement], None]:
	def on_advertisement(advertisement: Advertisement) -> None:
		if advertisement.address == target and not seen.done():
			seen.set_result(None)

	return on_advertisement


async def advertising(device: Device, target: Address) -> None:
	seen = asyncio.get_running_loop().create_future()
	with closing(EventWatcher()) as watcher:
		watcher.on(device, Device.EVENT_ADVERTISEMENT, resolve_when_seen(seen, target))
		async with scanning(device), asyncio.timeout(ADVERTISEMENT_TIMEOUT_SECONDS):
			await seen


@asynccontextmanager
async def le_connection(device: Device, target: Address) -> AsyncGenerator[Connection]:
	connection = await device.connect(target, timeout=CONNECT_TIMEOUT_SECONDS)
	try:
		yield connection
	finally:
		if device.connections.get(connection.handle) is connection:
			await connection.disconnect()


async def read_attribute(attribute: AttributeProxy[bytes]) -> Read:
	try:
		return Value(hex=(await attribute.read_value()).hex())
	except ATT_Error as error:
		return ReadFailed(error=str(error))


async def snapshot_descriptor(descriptor: DescriptorProxy) -> GattDescriptor:
	return GattDescriptor(
		handle=descriptor.handle,
		uuid=uuid_text(descriptor.type),
		name=descriptor.type.name or "",
		read=(
			await read_attribute(descriptor)
			if descriptor.type == GATT_REPORT_REFERENCE_DESCRIPTOR
			else NotRead()
		),
	)


async def snapshot_characteristic(characteristic: CharacteristicProxy[bytes]) -> GattCharacteristic:
	return GattCharacteristic(
		handle=characteristic.handle,
		uuid=uuid_text(characteristic.uuid),
		name=characteristic.uuid.name or "",
		properties=str(characteristic.properties),
		read=(
			await read_attribute(characteristic)
			if Characteristic.Properties.READ in characteristic.properties
			else NotRead()
		),
		descriptors=tuple(
			[
				await snapshot_descriptor(descriptor)
				for descriptor in await characteristic.discover_descriptors()
			]
		),
	)


async def snapshot_gatt(peer: Peer) -> tuple[GattService, ...]:
	return tuple(
		[
			GattService(
				handle=service.handle,
				end_handle=service.end_group_handle,
				uuid=uuid_text(service.uuid),
				name=service.uuid.name or "",
				characteristics=tuple(
					[
						await snapshot_characteristic(characteristic)
						for characteristic in service.characteristics
					]
				),
			)
			for service in peer.services
		]
	)


def report_recorder(
	handle: int, report_id: int, record: Record, clock: Clock
) -> Callable[[bytes], None]:
	return lambda value: record(
		Report(t=clock(), handle=handle, report_id=report_id, hex=bytes(value).hex())
	)


def indication_recorder(handle: int, record: Record, clock: Clock) -> Callable[[bytes], None]:
	return lambda value: record(Indication(t=clock(), handle=handle, hex=bytes(value).hex()))


def disconnection_recorder(record: Record, clock: Clock) -> Callable[[int], None]:
	return lambda reason: record(Disconnected(t=clock(), reason=reason))


async def subscribe(
	peer: Peer, gatt: tuple[GattService, ...], record: Record, clock: Clock
) -> None:
	report_ids = input_report_ids(gatt)
	for characteristic in (
		characteristic
		for service in peer.services
		for characteristic in service.characteristics
		if characteristic.handle in report_ids
	):
		await characteristic.subscribe(
			report_recorder(characteristic.handle, report_ids[characteristic.handle], record, clock)
		)
	for characteristic in peer.get_characteristics_by_uuid(GATT_SERVICE_CHANGED_CHARACTERISTIC):
		await characteristic.subscribe(indication_recorder(characteristic.handle, record, clock))


async def activate_hid(peer: Peer, gatt: tuple[GattService, ...]) -> None:
	for control_point in peer.get_characteristics_by_uuid(GATT_HID_CONTROL_POINT_CHARACTERISTIC):
		await control_point.write_value(EXIT_SUSPEND, with_response=False)
	for protocol_mode in (
		characteristic
		for characteristic in peer.get_characteristics_by_uuid(GATT_PROTOCOL_MODE_CHARACTERISTIC)
		if characteristic.handle in boot_protocol_handles(gatt)
	):
		await protocol_mode.write_value(REPORT_PROTOCOL, with_response=False)


class Linked(NamedTuple):
	connection: Connection


class LinkFailure(NamedTuple):
	error: str


async def establish(
	stack: AsyncExitStack, device: Device, target: Address, record: Record, clock: Clock
) -> Linked | LinkFailure:
	try:
		await advertising(device, target)
		connection = await stack.enter_async_context(le_connection(device, target))
		stack.enter_context(closing(EventWatcher())).on(
			connection, connection.EVENT_DISCONNECTION, disconnection_recorder(record, clock)
		)
		await connection.pair()
		peer = await stack.enter_async_context(Peer(connection))
		gatt = await snapshot_gatt(peer)
		record(Connected(t=clock(), peer=str(connection.peer_address), gatt=gatt))
		await subscribe(peer, gatt, record, clock)
		await activate_hid(peer, gatt)
	except (BaseBumbleError, TimeoutError) as error:
		return LinkFailure(error=repr(error))
	except asyncio.CancelledError as error:
		if (task := asyncio.current_task()) is not None and task.cancelling():
			raise
		return LinkFailure(error=repr(error))
	return Linked(connection=connection)


@asynccontextmanager
async def ring_link(
	device: Device, target: str, record: Record, clock: Clock
) -> AsyncGenerator[Linked | LinkFailure]:
	async with AsyncExitStack() as stack:
		yield await establish(stack, device, Address(target), record, clock)

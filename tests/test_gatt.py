from ring_gatt import hid_service

from page_turner.gatt import boot_protocol_handles, input_report_ids, report_maps
from page_turner.model import NotRead, ReadFailed, Value


def test_input_report_ids_skip_output_reports() -> None:
	assert input_report_ids((hid_service(Value(hex="01"), NotRead()),)) == {
		0x0013: 2,
		0x0017: 3,
		0x001B: 4,
		0x001F: 5,
	}


def test_report_maps_only_from_successful_reads() -> None:
	assert report_maps((hid_service(Value(hex="01"), Value(hex="050c0901")),)) == (
		bytes.fromhex("050c0901"),
	)
	assert report_maps((hid_service(Value(hex="01"), ReadFailed(error="nope")),)) == ()


def test_boot_protocol_handles_need_rewriting_to_report_protocol() -> None:
	assert boot_protocol_handles((hid_service(Value(hex="00"), NotRead()),)) == (0x0011,)
	assert boot_protocol_handles((hid_service(Value(hex="01"), NotRead()),)) == ()
	assert boot_protocol_handles((hid_service(NotRead(), NotRead()),)) == ()

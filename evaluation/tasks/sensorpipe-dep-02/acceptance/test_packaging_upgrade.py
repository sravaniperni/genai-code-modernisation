import importlib.metadata

import pytest

from sensorpipe.devices import Device, DeviceRegistry, is_legacy_firmware, parse_firmware
from sensorpipe.errors import RegistryError

LEGACY = ["FW-3.1b", "rev C build 7", "3.1-beta-hotfix"]


def test_packaging_is_pinned_to_24_2():
    assert importlib.metadata.version("packaging") == "24.2"


def test_release_versions_compare_numerically():
    assert parse_firmware("4.10.0") > parse_firmware("4.9.7")
    assert parse_firmware(" 4.2 ") == parse_firmware("4.2.0")
    assert parse_firmware("5.0.0rc1") < parse_firmware("5.0.0")
    assert not any(is_legacy_firmware(v) for v in ["4.2.0", "v5.0.1", "10.0.0.post1"])


@pytest.mark.parametrize("text", LEGACY)
def test_legacy_firmware_is_accepted_and_sorts_first(text):
    assert is_legacy_firmware(text)
    legacy = parse_firmware(text)
    assert legacy < parse_firmware("0.0.1")
    assert parse_firmware("0.0.1") > legacy
    assert not legacy > parse_firmware("0.0.1")
    assert sorted([parse_firmware("2.0"), legacy, parse_firmware("1.0")])[0] == legacy


def test_registry_with_legacy_devices():
    registry = DeviceRegistry.from_records([
        {"id": "NEW-2", "firmware": "4.10.0"},
        {"id": "OLD-1", "firmware": "FW-3.1b"},
        {"id": "NEW-1", "firmware": "3.1.0"},
        {"id": "OLD-2", "firmware": "rev C build 7"},
    ])
    order = [d.device_id for d in registry.by_firmware()]
    assert set(order[:2]) == {"OLD-1", "OLD-2"} and order[2:] == ["NEW-1", "NEW-2"]
    assert [d.device_id for d in registry.outdated("1.0")] == ["OLD-1", "OLD-2"]
    assert [d.device_id for d in registry.outdated("4.0")] == ["NEW-1", "OLD-1", "OLD-2"]
    for feature in ["utc_clock", "burst_mode", "edge_aggregation", "remote_calibration"]:
        assert not registry.supports("OLD-1", feature)
    assert registry.supports("NEW-1", "utc_clock")
    assert registry.supports("NEW-2", "edge_aggregation")
    with pytest.raises(RegistryError):
        registry.supports("OLD-1", "warp_drive")


def test_feature_gates_and_prereleases():
    registry = DeviceRegistry([Device("A", "m", "4.9.7"), Device("B", "m", "5.0.0rc1"), Device("C", "m", "5.0.0")])
    assert not registry.supports("A", "edge_aggregation")
    assert not registry.supports("B", "remote_calibration")  # pre-releases never pass a gate
    assert registry.supports("C", "remote_calibration") and registry.supports("C", "edge_aggregation")

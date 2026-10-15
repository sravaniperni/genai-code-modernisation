import pytest

from sensorpipe.devices import Device, DeviceRegistry, is_legacy_firmware, parse_firmware
from sensorpipe.errors import RegistryError


@pytest.fixture
def registry():
    return DeviceRegistry.from_records([
        {"id": "TT-101", "model": "RTD-4", "firmware": "4.2.0", "site": "plant-a", "channels": ["temp"]},
        {"id": "PT-201", "model": "PX-2", "firmware": "3.9.1", "site": "plant-a"},
        {"id": "FT-301", "model": "MAG-9", "firmware": "5.0.1", "site": "plant-b", "timezone": "Europe/Berlin"},
    ])


def test_register_and_lookup(registry):
    assert len(registry) == 3 and "TT-101" in registry
    assert registry.get("FT-301").timezone == "Europe/Berlin"
    assert [d.device_id for d in registry] == ["FT-301", "PT-201", "TT-101"]
    with pytest.raises(RegistryError):
        registry.get("XX-1")
    with pytest.raises(RegistryError):
        registry.register(Device("TT-101", "RTD-4", "4.3.0"))
    registry.register(Device("TT-101", "RTD-4", "4.3.0"), replace=True)
    assert registry.get("TT-101").firmware == "4.3.0"
    with pytest.raises(RegistryError, match="firmware"):
        DeviceRegistry.from_records([{"id": "X"}])


def test_feature_gates(registry):
    assert registry.supports("TT-101", "burst_mode")
    assert not registry.supports("PT-201", "burst_mode")
    assert registry.supports("PT-201", "utc_clock")
    assert registry.supports("FT-301", "remote_calibration")
    with pytest.raises(RegistryError):
        registry.supports("TT-101", "teleportation")


def test_gates_compare_numerically():
    registry = DeviceRegistry([Device("A", "m", "4.10.0"), Device("B", "m", "4.9.7")])
    assert registry.supports("A", "edge_aggregation")
    assert not registry.supports("B", "edge_aggregation")
    assert parse_firmware("4.10.0") > parse_firmware("4.9.7")


def test_outdated_devices(registry):
    assert [d.device_id for d in registry.outdated("4.2")] == ["PT-201"]
    assert [d.device_id for d in registry.outdated("5.1")] == ["FT-301", "PT-201", "TT-101"]


def test_legacy_firmware_strings():
    registry = DeviceRegistry([Device("OLD-1", "m", "FW-3.1b"), Device("NEW-1", "m", "3.1.0")])
    assert is_legacy_firmware("FW-3.1b") and not is_legacy_firmware("3.1.0")
    assert parse_firmware("FW-3.1b") < parse_firmware("0.1")
    assert not registry.supports("OLD-1", "utc_clock")
    assert registry.supports("NEW-1", "utc_clock")
    assert [d.device_id for d in registry.by_firmware()] == ["OLD-1", "NEW-1"]

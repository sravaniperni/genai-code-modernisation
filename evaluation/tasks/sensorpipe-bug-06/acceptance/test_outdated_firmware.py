import pytest

from sensorpipe.devices import Device, DeviceRegistry


@pytest.fixture
def fleet():
    return DeviceRegistry([
        Device("FT-301", "MAG-9", "10.1.0"),
        Device("PT-201", "PX-2", "9.10.0"),
        Device("TT-101", "RTD-4", "9.3.2"),
        Device("TT-102", "RTD-4", "10.0.0"),
        Device("LT-401", "RAD-1", "2.5"),
        Device("OLD-1", "RTD-1", "FW-3.1b"),
    ])


def ids(devices):
    return [d.device_id for d in devices]


def test_minimum_9_4(fleet):
    assert ids(fleet.outdated("9.4")) == ["LT-401", "OLD-1", "TT-101"]


def test_minimum_10_0(fleet):
    assert ids(fleet.outdated("10.0")) == ["LT-401", "OLD-1", "PT-201", "TT-101"]


def test_equal_versions_are_not_outdated(fleet):
    assert "TT-102" not in ids(fleet.outdated("10.0.0"))
    assert "TT-102" not in ids(fleet.outdated("10"))
    registry = DeviceRegistry([Device("A", "m", "4.2"), Device("B", "m", "4.2.0"), Device("C", "m", "4.1.99")])
    assert ids(registry.outdated("4.2.0")) == ["C"]
    assert ids(registry.outdated("4.2")) == ["C"]


def test_legacy_firmware_is_always_outdated(fleet):
    assert "OLD-1" in ids(fleet.outdated("0.1"))
    assert ids(fleet.outdated("0.1")) == ["OLD-1"]


def test_consistent_with_feature_gates(fleet):
    outdated = set(ids(fleet.outdated("4.10")))
    for device in fleet:
        assert (device.device_id in outdated) == (not fleet.supports(device.device_id, "edge_aggregation"))

"""Device registry with firmware version gating.

Older field devices report vendor firmware strings such as ``"FW-3.1b"`` instead of PEP 440 versions; those
are accepted, sort before every release version and never pass a feature gate."""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from typing import Any, Union

from packaging.specifiers import SpecifierSet
from packaging.version import LegacyVersion, Version, parse

from sensorpipe.errors import RegistryError

FirmwareVersion = Union[Version, LegacyVersion]

#: Minimum firmware per optional device feature.
FEATURE_GATES: dict[str, str] = {
    "utc_clock": ">=3.1",
    "burst_mode": ">=4.2",
    "edge_aggregation": ">=4.10",
    "remote_calibration": ">=5.0",
}


def parse_firmware(text: str) -> FirmwareVersion:
    """Parse a firmware string; vendor strings that are not PEP 440 versions sort before all releases."""
    return parse(str(text).strip())


def is_legacy_firmware(text: str) -> bool:
    return isinstance(parse_firmware(text), LegacyVersion)


@dataclass(frozen=True)
class Device:
    device_id: str
    model: str
    firmware: str
    site: str = ""
    timezone: str = "UTC"
    channels: tuple[str, ...] = field(default_factory=tuple)

    @property
    def firmware_version(self) -> FirmwareVersion:
        return parse_firmware(self.firmware)

    @classmethod
    def from_record(cls, record: Mapping[str, Any]) -> Device:
        try:
            return cls(
                device_id=str(record["id"]), model=str(record.get("model", "")), firmware=str(record["firmware"]),
                site=str(record.get("site", "")), timezone=str(record.get("timezone", "UTC")),
                channels=tuple(str(c) for c in record.get("channels", ())),
            )
        except KeyError as exc:
            raise RegistryError(f"device record is missing {exc.args[0]!r}") from None


class DeviceRegistry:
    """In-memory registry of field devices keyed by device id."""

    def __init__(self, devices: Iterable[Device] = ()):
        self._devices: dict[str, Device] = {}
        for device in devices:
            self.register(device)

    @classmethod
    def from_records(cls, records: Iterable[Mapping[str, Any]]) -> DeviceRegistry:
        return cls(Device.from_record(r) for r in records)

    def register(self, device: Device, replace: bool = False) -> None:
        if device.device_id in self._devices and not replace:
            raise RegistryError(f"device {device.device_id!r} is already registered")
        self._devices[device.device_id] = device

    def get(self, device_id: str) -> Device:
        try:
            return self._devices[device_id]
        except KeyError:
            raise RegistryError(f"unknown device {device_id!r}") from None

    def __contains__(self, device_id: object) -> bool:
        return device_id in self._devices

    def __len__(self) -> int:
        return len(self._devices)

    def __iter__(self) -> Iterator[Device]:
        return iter(sorted(self._devices.values(), key=lambda d: d.device_id))

    def supports(self, device_id: str, feature: str) -> bool:
        """Whether the device's firmware satisfies the gate of ``feature``."""
        if feature not in FEATURE_GATES:
            raise RegistryError(f"unknown feature {feature!r}")
        version = self.get(device_id).firmware_version
        if isinstance(version, LegacyVersion):
            return False
        return SpecifierSet(FEATURE_GATES[feature]).contains(version)

    def outdated(self, minimum: str) -> list[Device]:
        """Devices running firmware older than ``minimum``."""
        floor = parse_firmware(minimum)
        return [d for d in self if d.firmware_version < floor]

    def by_firmware(self) -> list[Device]:
        """Devices ordered from oldest to newest firmware (ties by id)."""
        return sorted(self, key=lambda d: d.firmware_version)

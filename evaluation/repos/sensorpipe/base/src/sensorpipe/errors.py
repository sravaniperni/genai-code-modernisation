"""Exception hierarchy shared by all sensorpipe modules."""


class SensorPipeError(Exception):
    """Base class for every error raised by sensorpipe."""


class IngestError(SensorPipeError):
    """Input data could not be parsed into readings."""


class UnitError(SensorPipeError, ValueError):
    """Unknown unit or conversion between incompatible dimensions."""


class CalibrationError(SensorPipeError, ValueError):
    """Invalid calibration data or a value outside a calibrated range."""


class ConfigError(SensorPipeError):
    """Invalid pipeline configuration."""


class RegistryError(SensorPipeError, KeyError):
    """Unknown device or feature in the device registry."""

    def __str__(self) -> str:  # KeyError would otherwise repr() the message
        return str(self.args[0]) if self.args else ""


class ArchiveError(SensorPipeError):
    """A batch archive is unreadable or contains unsafe members."""

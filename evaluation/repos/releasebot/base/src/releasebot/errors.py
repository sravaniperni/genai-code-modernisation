"""Exception hierarchy shared by all releasebot modules."""


class ReleasebotError(Exception):
    """Base class for every error raised deliberately by releasebot."""


class ConfigError(ReleasebotError):
    """The project configuration is missing or invalid."""


class InvalidVersionError(ReleasebotError, ValueError):
    """A string is not a valid semantic version."""


class TemplateNotFoundError(ReleasebotError, LookupError):
    """A changelog or release-notes template does not exist."""


class HostingError(ReleasebotError):
    """The code-hosting API returned an error or could not be reached."""

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class PluginError(ReleasebotError):
    """A publisher plugin is unknown or unusable."""


class PublishError(ReleasebotError):
    """A publisher could not complete the release."""


class HookError(ReleasebotError):
    """A release hook is malformed or failed."""


class BundleError(ReleasebotError):
    """A release bundle could not be created or unpacked."""

"""Exception hierarchy shared by every ledgerkit module."""


class LedgerError(Exception):
    """Base class for all ledgerkit errors."""


class FormatError(LedgerError):
    """Malformed or incompatible import/export data."""


class _LookupFailure(LedgerError, KeyError):
    def __str__(self) -> str:  # KeyError would repr() the message
        return str(self.args[0]) if self.args else ""


class AccountNotFoundError(_LookupFailure): ...

class TemplateNotFoundError(_LookupFailure): ...

class UnknownCurrencyError(LedgerError): ...

class CurrencyMismatchError(LedgerError): ...

class DuplicateAccountError(LedgerError): ...

class UnbalancedEntryError(LedgerError): ...

class PeriodClosedError(LedgerError): ...

class RateNotFoundError(LedgerError): ...

class SignatureError(LedgerError): ...

class BackupError(LedgerError): ...

import importlib.metadata
import json
from datetime import date

import pytest
from click.testing import CliRunner

from ledgerkit.accounts import Account, AccountType, ChartOfAccounts
from ledgerkit.formats import dump_ledger
from ledgerkit.journal import JournalEntry, Ledger, Posting


def _ledger() -> Ledger:
    chart = ChartOfAccounts([
        Account("1000", "Cash", AccountType.ASSET),
        Account("1100", "Accounts Receivable", AccountType.ASSET),
        Account("3000", "Owner's Capital with an extraordinarily long descriptive name", AccountType.EQUITY),
        Account("4000", "Sales", AccountType.INCOME),
        Account("6100", "Rent", AccountType.EXPENSE),
    ])
    ledger = Ledger(chart)
    ledger.post(JournalEntry(date(2024, 1, 2), "Capital", (Posting.debit("1000", "5000"), Posting.credit("3000", "5000"))))
    ledger.post(JournalEntry(date(2024, 1, 9), "Sale", (Posting.debit("1100", "1234.50"), Posting.credit("4000", "1234.50"))))
    ledger.post(JournalEntry(date(2024, 1, 12), "Rent", (Posting.debit("6100", "700"), Posting.credit("1000", "700"))))
    return ledger


@pytest.fixture
def books(tmp_path):
    path = tmp_path / "books.json"
    path.write_text(dump_ledger(_ledger()), encoding="utf-8")
    return path


def invoke(*args, env=None):
    from ledgerkit.cli import cli
    return CliRunner().invoke(cli, list(args), env=env)


def test_click_is_pinned_to_8_1_8():
    assert importlib.metadata.version("click") == "8.1.8"


def test_balance_and_errors(books):
    result = invoke("--ledger", str(books), "balance", "4000")
    assert result.exit_code == 0, result.output
    assert result.output == "4000 Sales: 1,234.50 USD\n"
    result = invoke("--ledger", str(books), "balance", "1000", "--as-of", "2024-01-10")
    assert result.output == "1000 Cash: 5,000.00 USD\n"
    missing = invoke("--ledger", str(books), "balance", "9999")
    assert missing.exit_code == 1
    assert "Error: no account with code '9999'" in missing.output
    no_ledger = invoke("balance", "1000")
    assert no_ledger.exit_code == 2
    assert "no ledger file given" in no_ledger.output


def test_environment_variable_selects_ledger(books):
    result = invoke("balance", "6100", env={"LEDGERKIT_FILE": str(books)})
    assert result.exit_code == 0, result.output
    assert result.output == "6100 Rent: 700.00 USD\n"


def test_json_and_csv_rendering(books):
    rows = json.loads(invoke("--ledger", str(books), "--format", "json", "trial-balance").output)
    assert rows[0] == {"code": "1000", "account": "Cash", "debit": "4300", "credit": "0"}
    assert rows[-1] == {"code": "", "account": "Total", "debit": "6234.50", "credit": "6234.50"}
    csv_lines = invoke("--ledger", str(books), "--format", "csv", "trial-balance").output.splitlines()
    assert csv_lines[0] == "code,account,debit,credit"
    assert csv_lines[-1] == ",Total,6234.50,6234.50"


def test_table_respects_terminal_width(books):
    wide = invoke("--ledger", str(books), "trial-balance", env={"COLUMNS": "200"})
    assert wide.exit_code == 0, wide.output
    assert "Owner's Capital with an extraordinarily long descriptive name" in wide.output
    assert max(len(line) for line in wide.output.splitlines()) > 60
    narrow = invoke("--ledger", str(books), "trial-balance", env={"COLUMNS": "40"})
    assert narrow.exit_code == 0, narrow.output
    lines = narrow.output.splitlines()
    assert lines[0].startswith("code  account")
    assert all(len(line) <= 40 for line in lines)
    assert any(line.endswith("…") for line in lines)


def test_import_csv_command(books, tmp_path):
    source = tmp_path / "feb.csv"
    source.write_text("date,reference,description,account,debit,credit\n"
                      "2024-02-02,R1,Rent,6100,\"1,000.00\",\n2024-02-02,R1,Rent,1000,,\"1,000.00\"\n", encoding="utf-8")
    result = invoke("--ledger", str(books), "import-csv", str(source))
    assert result.exit_code == 0, result.output
    assert result.output == "imported 1 entries\n"
    assert invoke("--ledger", str(books), "balance", "6100").output == "6100 Rent: 1,700.00 USD\n"


def _completions(args, incomplete):
    from click.shell_completion import ShellComplete

    from ledgerkit.cli import cli
    return ShellComplete(cli, {}, "ledgerkit", "_LEDGERKIT_COMPLETE").get_completions(args, incomplete)


def test_account_completion_offers_codes_with_names(books):
    items = _completions(["--ledger", str(books), "balance"], "1")
    assert [item.value for item in items] == ["1000", "1100"]
    assert [item.help for item in items] == ["Cash", "Accounts Receivable"]
    assert [item.value for item in _completions(["--ledger", str(books), "balance"], "")] == \
        ["1000", "1100", "3000", "4000", "6100"]
    assert _completions(["--ledger", str(books), "balance"], "7") == []


def test_account_completion_without_usable_ledger(tmp_path):
    assert _completions(["balance"], "1") == []
    assert _completions(["--ledger", str(tmp_path / "missing.json"), "balance"], "1") == []

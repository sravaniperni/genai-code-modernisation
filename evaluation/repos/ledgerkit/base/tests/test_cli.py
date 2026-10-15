import json

import pytest
from click.testing import CliRunner

from ledgerkit.cli import cli
from ledgerkit.formats import dump_ledger


@pytest.fixture
def books(ledger, tmp_path):
    path = tmp_path / "books.json"
    path.write_text(dump_ledger(ledger), encoding="utf-8")
    return path


def run(*args, env=None):
    result = CliRunner().invoke(cli, list(args), env=env)
    return result


def test_balance_command(books):
    result = run("--ledger", str(books), "balance", "4000")
    assert result.exit_code == 0, result.output
    assert result.output == "4000 Sales: 2,900.00 USD\n"
    assert "no account with code '9999'" in run("--ledger", str(books), "balance", "9999").output


def test_trial_balance_formats(books):
    table = run("--ledger", str(books), "trial-balance")
    assert table.exit_code == 0, table.output
    assert table.output.splitlines()[0].split() == ["code", "account", "debit", "credit"]
    assert "Total" in table.output and "12,900.00" in table.output
    rows = json.loads(run("--ledger", str(books), "--format", "json", "trial-balance").output)
    assert rows[-1] == {"code": "", "account": "Total", "debit": "12900.00", "credit": "12900.00"}
    csv_text = run("--ledger", str(books), "--format", "csv", "trial-balance").output
    assert csv_text.splitlines()[1] == "1000,Cash,9200,0"


def test_import_csv_command(books, tmp_path):
    source = tmp_path / "feb.csv"
    source.write_text("date,reference,description,account,debit,credit\n"
                      "2024-02-02,A1,Ads,6200,\"1,000.00\",\n2024-02-02,A1,Ads,1000,,\"1,000.00\"\n", encoding="utf-8")
    result = run("--ledger", str(books), "import-csv", str(source))
    assert result.exit_code == 0, result.output
    assert result.output.strip() == "imported 1 entries"
    assert run("--ledger", str(books), "balance", "6200").output == "6200 Marketing: 1,000.00 USD\n"


def test_missing_ledger_option():
    result = run("balance", "1000")
    assert result.exit_code != 0
    assert "no ledger file given" in result.output

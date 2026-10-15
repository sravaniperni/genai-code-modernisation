from datetime import date
from decimal import Decimal

import pytest
from click.testing import CliRunner

from ledgerkit.accounts import Account, AccountType, ChartOfAccounts
from ledgerkit.cli import cli
from ledgerkit.formats import dump_ledger, load_ledger
from ledgerkit.importers import read_csv
from ledgerkit.journal import Ledger
from ledgerkit.money import parse_amount

EU_CSV = """date,reference,description,account,debit,credit,currency
2024-02-01,B1,Miete,6100,"1.234,56",,EUR
2024-02-01,B1,Miete,1200,,"1.234,56",EUR
2024-02-02,B2,Kaffee,6100,"12,50",,EUR
2024-02-02,B2,Kaffee,1200,,"12,50",EUR
2024-02-03,B3,Gutschrift,1200,"€ 7,00",,EUR
2024-02-03,B3,Gutschrift,6100,"(7,00)","",EUR
"""


@pytest.mark.parametrize(("text", "expected"), [
    ("1.234,56", "1234.56"), ("12,50", "12.50"), ("1.234.567,89", "1234567.89"), ("-1.000,00", "-1000.00"),
    ("(3,10)", "-3.10"), ("0,5", "0.5"), ("€ 7,00", "7.00"), ("2.000", "2000"), ("1.000,00-", "-1000.00"),
])
def test_decimal_comma_amounts(text, expected):
    assert parse_amount(text, ",", ".") == Decimal(expected)


@pytest.mark.parametrize(("text", "decimal_sep", "thousands_sep", "expected"), [
    ("1,234.56", ".", ",", "1234.56"), ("(45.10)", ".", ",", "-45.10"), ("1'234.56", ".", "'", "1234.56"),
    ("1 234,56", ",", " ", "1234.56"), ("1234,5", ",", "", "1234.5"),
])
def test_other_formats_unchanged(text, decimal_sep, thousands_sep, expected):
    assert parse_amount(text, decimal_sep, thousands_sep) == Decimal(expected)
    assert parse_amount("1,234.56") == Decimal("1234.56")


def test_read_csv_with_european_format():
    entries = read_csv(EU_CSV, decimal_sep=",", thousands_sep=".")
    assert [[p.amount.amount for p in e.postings] for e in entries] == [
        [Decimal("1234.56"), Decimal("-1234.56")], [Decimal("12.50"), Decimal("-12.50")],
        [Decimal("7.00"), Decimal("-7.00")]]


def test_import_csv_command_with_european_format(tmp_path):
    chart = ChartOfAccounts([Account("1200", "Bank EUR", AccountType.ASSET, "EUR"),
                             Account("6100", "Rent", AccountType.EXPENSE, "EUR")])
    books = tmp_path / "books.json"
    books.write_text(dump_ledger(Ledger(chart)), encoding="utf-8")
    source = tmp_path / "export.csv"
    source.write_text(EU_CSV, encoding="utf-8")
    result = CliRunner().invoke(cli, ["--ledger", str(books), "import-csv", "--decimal", ",", "--thousands", ".",
                                      str(source)])
    assert result.exit_code == 0, result.output
    ledger, _ = load_ledger(books.read_text(encoding="utf-8"))
    assert ledger.balance("6100").amount == Decimal("1240.06")
    assert ledger.balance("1200").amount == Decimal("-1240.06")
    assert ledger.entries[0].date == date(2024, 2, 1)

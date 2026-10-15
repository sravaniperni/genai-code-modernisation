import importlib.metadata
from datetime import date
from decimal import Decimal

import pydantic
import pytest

from ledgerkit.errors import FormatError
from ledgerkit.journal import JournalEntry, Posting
from ledgerkit.schemas import EntryIn, PostingIn, entry_payload, parse_entry

PAYLOAD = {"date": "2024-05-02", "description": "  Office rent May ", "reference": " R-5 ",
           "postings": [{"account": " 6100", "debit": "1500.00", "memo": " May "},
                        {"account": "1000 ", "credit": "1500.00", "currency": " USD "}]}


def problems(payload):
    with pytest.raises(FormatError) as info:
        parse_entry(payload)
    return str(info.value)


def test_pydantic_is_pinned_to_2_11_7():
    assert importlib.metadata.version("pydantic") == "2.11.7"


def test_models_are_native_pydantic_2_models():
    assert issubclass(EntryIn, pydantic.BaseModel) and issubclass(PostingIn, pydantic.BaseModel)
    model = EntryIn.model_validate(PAYLOAD)
    dumped = model.model_dump()
    assert dumped["description"] == "Office rent May"
    assert dumped["postings"][0]["account"] == "6100"
    assert dumped["postings"][1]["currency"] == "USD"
    assert EntryIn.model_validate(dumped) == model


def test_parse_entry_strips_whitespace_and_builds_entry():
    entry = parse_entry(PAYLOAD)
    assert isinstance(entry, JournalEntry)
    assert (entry.date, entry.description, entry.reference) == (date(2024, 5, 2), "Office rent May", "R-5")
    assert [(p.account, p.amount.amount, p.amount.currency, p.memo) for p in entry.postings] == [
        ("6100", Decimal("1500.00"), "USD", "May"), ("1000", Decimal("-1500.00"), "USD", "")]


def test_multi_currency_entries_balance_per_currency():
    entry = parse_entry({"date": "2024-05-03", "description": "FX", "postings": [
        {"account": "1200", "debit": "90.5", "currency": "EUR"}, {"account": "4100", "credit": "90.5", "currency": "EUR"},
        {"account": "1000", "debit": "100", "currency": "USD"}, {"account": "4000", "credit": "100"}]})
    assert {p.amount.currency for p in entry.postings} == {"EUR", "USD"}
    message = problems({"date": "2024-05-03", "description": "FX", "postings": [
        {"account": "1200", "debit": "90", "currency": "EUR"}, {"account": "1000", "credit": "90", "currency": "USD"}]})
    assert "postings: " in message and "does not balance in EUR, USD" in message


def test_field_rules():
    def posting(**kwargs):
        return {**PAYLOAD, "postings": [{"account": "6100", "debit": "10", **kwargs}, {"account": "1000", "credit": "10"}]}

    assert problems(posting(account="61A0")).startswith("postings.0.account: ")
    assert problems(posting(account="12")).startswith("postings.0.account: ")
    assert problems(posting(currency="usd")).startswith("postings.0.currency: ")
    assert "unsupported currency XYZ" in problems(posting(currency="XYZ"))
    assert problems(posting(debit="-10")).startswith("postings.0.debit: ")
    assert problems(posting(debit="10.0000001")).startswith("postings.0.debit: ")
    assert "exactly one of debit or credit must be greater than zero" in problems(posting(credit="10"))
    assert problems(posting(colour="red")).startswith("postings.0.colour: ")
    assert problems({**PAYLOAD, "description": "   "}).startswith("description: ")
    assert problems({**PAYLOAD, "description": "x" * 201}).startswith("description: ")
    assert problems({**PAYLOAD, "approved": True}).startswith("approved: ")
    assert problems({**PAYLOAD, "date": "2024-02-30"}).startswith("date: ")
    assert problems({**PAYLOAD, "postings": PAYLOAD["postings"][:1]}).startswith("postings: ")


def test_all_problems_are_reported_together():
    message = problems({"date": "yesterday", "description": "", "postings": [{"account": "x", "debit": "1"},
                                                                          {"account": "1000", "credit": "1"}]})
    fields = [part.split(":")[0] for part in message.split("; ")]
    assert {"date", "description", "postings.0.account"} <= set(fields)


def test_entry_payload_round_trip():
    entry = JournalEntry(date(2024, 6, 1), "Mixed", (Posting.debit("6100", "12.345678"), Posting.credit("1000", "12.345678"),
                                                     Posting.debit("1200", "3", "EUR", memo="fee"),
                                                     Posting.credit("4100", "3", "EUR")), reference="M-1")
    payload = entry_payload(entry)
    assert payload == {"date": "2024-06-01", "description": "Mixed", "reference": "M-1", "postings": [
        {"account": "6100", "debit": "12.345678", "credit": "0", "currency": "USD", "memo": ""},
        {"account": "1000", "debit": "0", "credit": "12.345678", "currency": "USD", "memo": ""},
        {"account": "1200", "debit": "3", "credit": "0", "currency": "EUR", "memo": "fee"},
        {"account": "4100", "debit": "0", "credit": "3", "currency": "EUR", "memo": ""}]}
    assert parse_entry(payload).postings == entry.postings

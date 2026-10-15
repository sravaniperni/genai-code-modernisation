from datetime import date
from decimal import Decimal

from ledgerkit.store import LedgerStore


def test_store_round_trip(ledger):
    store = LedgerStore()
    assert store.save_chart(ledger.chart) == len(ledger.chart)
    for entry in ledger.entries:
        store.save_entry(entry)
    assert store.count_entries() == 4
    restored = store.load_ledger()
    assert restored.chart.to_list() == ledger.chart.to_list()
    assert [(e.entry_id, e.date, e.description, e.postings) for e in restored.entries] == \
        [(e.entry_id, e.date, e.description, e.postings) for e in ledger.entries]
    assert [e.to_dict()["created_at"] for e in restored.entries] == [e.to_dict()["created_at"] for e in ledger.entries]
    assert [e.description for e in store.load_entries(start=date(2024, 1, 12))] == ["Cash sale", "January rent"]


def test_store_aggregates_and_deletes(ledger):
    store = LedgerStore()
    store.save_chart(ledger.chart)
    store.save_chart(ledger.chart)  # saving twice updates instead of failing
    for entry in ledger.entries:
        store.save_entry(entry)
    totals = store.account_totals()
    assert totals["1000"] == (Decimal("10400.00"), Decimal("1200.00"))
    assert store.account_totals(as_of=date(2024, 1, 12))["4000"] == (Decimal("0.00"), Decimal("2500.00"))
    assert store.delete_entry(ledger.entries[0].entry_id)
    assert not store.delete_entry("missing")
    assert store.count_entries() == 3
    assert "3000" not in store.account_totals()

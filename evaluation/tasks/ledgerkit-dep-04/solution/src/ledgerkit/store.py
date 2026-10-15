"""SQL persistence for the chart of accounts and the journal (SQLAlchemy Core).

Amounts are stored as integers in minor units so that SQL aggregates stay exact.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (Column, Date, ForeignKey, Integer, MetaData, String, Table, Text, case, create_engine, func,
                        select, text)

from ledgerkit.accounts import ChartOfAccounts
from ledgerkit.journal import JournalEntry, Ledger, Posting
from ledgerkit.money import Money, minor_digits

metadata = MetaData()
accounts_table = Table(
    "accounts", metadata,
    Column("code", String(20), primary_key=True), Column("name", String(200), nullable=False),
    Column("type", String(20), nullable=False), Column("currency", String(3), nullable=False),
    Column("parent", String(20)),
)
entries_table = Table(
    "entries", metadata,
    Column("id", String(32), primary_key=True), Column("date", Date, nullable=False, index=True),
    Column("description", Text, nullable=False), Column("reference", String(64), nullable=False),
    Column("created_at", String(40), nullable=False),
)
postings_table = Table(
    "postings", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("entry_id", String(32), ForeignKey("entries.id"), nullable=False, index=True),
    Column("line", Integer, nullable=False), Column("account", String(20), ForeignKey("accounts.code"), nullable=False),
    Column("minor_units", Integer, nullable=False), Column("currency", String(3), nullable=False),
    Column("memo", Text, nullable=False),
)


def _from_minor(units: int, currency: str) -> Decimal:
    return Decimal(units).scaleb(-minor_digits(currency))


class LedgerStore:
    def __init__(self, url: str = "sqlite://"):
        self.engine = create_engine(url)
        metadata.create_all(self.engine)

    def save_chart(self, chart: ChartOfAccounts) -> int:
        """Insert new accounts and update existing ones; returns the number of accounts written."""
        with self.engine.begin() as conn:
            known = set(conn.execute(select(accounts_table.c.code)).scalars())
            for account in chart:
                row = account.to_dict()
                if row["code"] in known:
                    conn.execute(accounts_table.update().where(accounts_table.c.code == row["code"]).values(**row))
                else:
                    conn.execute(accounts_table.insert().values(**row))
        return len(chart)

    def load_chart(self) -> ChartOfAccounts:
        with self.engine.connect() as conn:
            rows = conn.execute(select(accounts_table).order_by(accounts_table.c.code)).mappings().all()
        return ChartOfAccounts.from_list(dict(row) for row in rows)

    def save_entry(self, entry: JournalEntry) -> None:
        lines = [{"entry_id": entry.entry_id, "line": i, "account": p.account, "currency": p.amount.currency,
                  "minor_units": int(p.amount.rounded().amount.scaleb(minor_digits(p.amount.currency))),
                  "memo": p.memo} for i, p in enumerate(entry.postings)]
        with self.engine.begin() as conn:
            conn.execute(entries_table.insert().values(
                id=entry.entry_id, date=entry.date, description=entry.description, reference=entry.reference,
                created_at=entry.created_at.isoformat()))
            conn.execute(postings_table.insert(), lines)

    def load_entries(self, start: date | None = None) -> list[JournalEntry]:
        """Stored entries (optionally only those dated ``start`` or later), ordered by date."""
        query = select(entries_table).order_by(entries_table.c.date, entries_table.c.id)
        with self.engine.connect() as conn:
            rows = conn.execute(query if start is None else query.where(entries_table.c.date >= start)).mappings().all()
            lines = conn.execute(select(postings_table).order_by(postings_table.c.entry_id, postings_table.c.line))
            lines = lines.mappings().all()
        postings: dict[str, list[Posting]] = {}
        for p in lines:
            amount = Money(_from_minor(p["minor_units"], p["currency"]), p["currency"])
            postings.setdefault(p["entry_id"], []).append(Posting(p["account"], amount, p["memo"]))
        return [JournalEntry(r["date"], r["description"], tuple(postings.get(r["id"], ())), reference=r["reference"],
                             entry_id=r["id"], created_at=datetime.fromisoformat(r["created_at"])) for r in rows]

    def load_ledger(self) -> Ledger:
        ledger = Ledger(self.load_chart())
        ledger.post_many(self.load_entries())
        return ledger

    def account_totals(self, as_of: date | None = None) -> dict[str, tuple[Decimal, Decimal]]:
        """``{account: (debits, credits)}`` aggregated in SQL, optionally up to and including ``as_of``."""
        units = postings_table.c.minor_units
        debits = func.sum(case((units > 0, units), else_=0)).label("debits")
        credits = func.sum(case((units < 0, -units), else_=0)).label("credits")
        query = (select(postings_table.c.account, postings_table.c.currency, debits, credits)
                 .select_from(postings_table.join(entries_table))
                 .group_by(postings_table.c.account, postings_table.c.currency))
        if as_of is not None:
            query = query.where(entries_table.c.date <= as_of)
        with self.engine.connect() as conn:
            rows = conn.execute(query).mappings().all()
        return {row["account"]: (_from_minor(row["debits"], row["currency"]), _from_minor(row["credits"], row["currency"]))
                for row in rows}

    def delete_entry(self, entry_id: str) -> bool:
        with self.engine.begin() as conn:
            conn.execute(text("DELETE FROM postings WHERE entry_id = :id"), {"id": entry_id})
            result = conn.execute(text("DELETE FROM entries WHERE id = :id"), {"id": entry_id})
        return result.rowcount > 0

    def count_entries(self) -> int:
        with self.engine.connect() as conn:
            return conn.execute(text("SELECT COUNT(*) FROM entries")).scalar_one()

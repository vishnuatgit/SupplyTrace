"""
Every analysed invoice is recorded here with its fingerprint (a hash of the
file) and key fields, and compared with the invoices recorded before it.

Two kinds of duplicate are flagged, always pointing at the earliest match
(for likely duplicates, the earliest invoice that was not itself flagged):

  exact   the very same file content (same SHA-256), checked before.
  likely  a different file that is probably the same invoice:
            - same supplier and same invoice (transaction) ID, or
            - same supplier and same amount, issued within DATE_WINDOW_DAYS of
              each other (only when both invoices have an issue date).

Likely duplicates need to know the supplier, so an invoice without one can only be
an exact duplicate. Invoices recorded as demo data (origin "demo") are never an
"exact" match: they are the starter samples, and checking a sample for the first
time is not a duplicate.
"""

from datetime import UTC, date, datetime

from sqlalchemy import Engine, and_, func, insert, select

from src.invoices.fields import parse_issue_date
from src.storage.schema import invoices, reviews

EXACT, LIKELY = "exact", "likely"
DEMO_ORIGIN = "demo"
DATE_WINDOW_DAYS = 7
AMOUNT_TOLERANCE = 0.005  # amounts are equal when they match to the cent


def dates_close(first: str, second: str, days: int = DATE_WINDOW_DAYS) -> bool:
    """True when both are real dates and fall within `days` days of each other."""
    a, b = parse_issue_date(first), parse_issue_date(second)
    if not isinstance(a, date) or not isinstance(b, date):
        return False
    return abs((a - b).days) <= days


def _now() -> str:
    return datetime.now(UTC).isoformat()


class InvoiceStore:
    def __init__(self, engine: Engine):
        self.engine = engine

    def count(self) -> int:
        with self.engine.connect() as conn:
            return conn.execute(select(func.count()).select_from(invoices)).scalar()

    def record(self, result: dict, content_hash: str, origin: str) -> dict | None:
        """
        Compares the invoice with those recorded before, records it (with the flag it
        got) and returns the flag: {"kind", "reason", "of": {...}}, or None when it is
        not a duplicate. The comparison and the insert share one transaction.
        """
        fields = result["key_fields"]
        with self.engine.begin() as conn:
            earlier, kind, reason = self._find_duplicate(conn, fields, result["id"], content_hash)
            conn.execute(
                insert(invoices).values(
                    content_hash=content_hash,
                    filename=result["filename"],
                    invoice_id=result["id"],
                    vendor_key=fields["vendor_key"],
                    supplier_id=fields["supplier_id"],
                    supplier_name=fields["supplier_name"],
                    amount=fields["amount"],
                    amount_text=result["fields"]["AMOUNT"]["value"],
                    currency=fields["currency"],
                    issue_date=fields["issue_date"],
                    validation_status=result["status"],
                    risk_score=_score(result),
                    origin=origin,
                    seen_at=_now(),
                    duplicate_kind=kind,
                    duplicate_of=earlier.id if earlier else None,
                    duplicate_reason=reason,
                )
            )
            return self._flag(conn, earlier, kind, reason)

    def flag_for(self, content_hash: str) -> dict | None:
        """The duplicate flag the first check of this file content got, or None."""
        with self.engine.connect() as conn:
            row = conn.execute(
                select(invoices)
                .where(invoices.c.content_hash == content_hash)
                .order_by(invoices.c.id)
                .limit(1)
            ).first()
            if row is None or row.duplicate_kind is None:
                return None
            earlier = conn.execute(
                select(invoices).where(invoices.c.id == row.duplicate_of)
            ).first()
            return self._flag(conn, earlier, row.duplicate_kind, row.duplicate_reason)

    # Internals

    @staticmethod
    def _find_duplicate(conn, fields, invoice_id, content_hash):
        """(earliest earlier invoice, kind, reason), or (None, None, None)."""
        exact = conn.execute(
            select(invoices)
            .where(invoices.c.content_hash == content_hash, invoices.c.origin != DEMO_ORIGIN)
            .order_by(invoices.c.id)
            .limit(1)
        ).first()
        if exact:
            return exact, EXACT, "The same file content was checked before."

        vendor = fields["vendor_key"]
        if not vendor:
            return None, None, None
        # A likely match must be an original: an invoice that was itself flagged as a
        # duplicate is not something later invoices are compared with.
        same_vendor = and_(
            invoices.c.vendor_key == vendor,
            invoices.c.content_hash != content_hash,
            invoices.c.duplicate_kind.is_(None),
        )

        if invoice_id:
            same_id = conn.execute(
                select(invoices)
                .where(same_vendor, invoices.c.invoice_id == invoice_id)
                .order_by(invoices.c.id)
                .limit(1)
            ).first()
            if same_id:
                return same_id, LIKELY, f"Same supplier and the same invoice ID ({invoice_id})."

        amount = fields["amount"]
        if amount is not None and fields["issue_date"]:
            same_amount = conn.execute(
                select(invoices)
                .where(
                    same_vendor,
                    invoices.c.issue_date != "",
                    func.abs(invoices.c.amount - amount) < AMOUNT_TOLERANCE,
                )
                .order_by(invoices.c.id)
            ).all()
            for row in same_amount:
                if dates_close(fields["issue_date"], row.issue_date):
                    return (
                        row,
                        LIKELY,
                        f"Same supplier and amount ({row.amount_text}), issued "
                        f"{row.issue_date} and {fields['issue_date']}, within "
                        f"{DATE_WINDOW_DAYS} days.",
                    )
        return None, None, None

    @staticmethod
    def _flag(conn, earlier, kind, reason) -> dict | None:
        if earlier is None:
            return None
        review_id = conn.execute(
            select(reviews.c.id).where(reviews.c.content_hash == earlier.content_hash)
        ).scalar()
        return {
            "kind": kind,
            "reason": reason,
            "of": {
                "id": earlier.id,
                "filename": earlier.filename,
                "invoice_id": earlier.invoice_id,
                "seen_at": earlier.seen_at,
                "review_id": review_id,
            },
        }


def _score(result: dict):
    score = result["prediction"]["risk_score"]
    return score if isinstance(score, int | float) else None

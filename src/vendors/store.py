"""
The vendor directory. A vendor is a supplier as parsed from the invoices (see
src.invoices.fields.vendor_key): there is no separate list to maintain, the
vendors and their statistics are computed from the recorded invoices.

People can add two things to a vendor: free-text notes and a "trusted" flag. Both
are stored and shown, and neither takes part in validation: the rules, the risk
score and the duplicate check never read them.
"""

import hashlib
from datetime import UTC, datetime

from sqlalchemy import Engine, case, func, select

from src.storage.schema import invoices, reviews, vendor_profiles

STATUSES = ("VALID", "INVALID", "REQUIRES_REVIEW")
SORTS = ("name", "invoices", "total", "duplicates", "risk", "last_seen")


class VendorNotFound(Exception):
    """No invoice belongs to a vendor with this id (HTTP 404)."""


def vendor_id(key: str) -> str:
    """A short, URL-safe id for a vendor key (the key itself is free text)."""
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]


def _now() -> str:
    return datetime.now(UTC).isoformat()


class VendorStore:
    def __init__(self, engine: Engine):
        self.engine = engine

    def list(self, q=None, trusted=None, sort="name") -> dict:
        """
        Every vendor with its statistics, filtered by a search over name and ID and by
        the trusted flag, sorted by name (A to Z) or by a statistic (largest first).
        """
        with self.engine.connect() as conn:
            vendors = self._vendors(conn)
        total = len(vendors)
        trusted_count = sum(v["trusted"] for v in vendors)
        if q:
            needle = q.casefold()
            vendors = [
                v
                for v in vendors
                if needle in v["name"].casefold() or needle in v["supplier_id"].casefold()
            ]
        if trusted is not None:
            vendors = [v for v in vendors if v["trusted"] == trusted]
        # (what to sort by, largest first?) The name is A to Z, every statistic is largest first.
        keys = {
            "name": (lambda v: v["name"].casefold(), False),
            "invoices": (lambda v: v["invoice_count"], True),
            "total": (lambda v: v["total_amount"], True),
            "duplicates": (lambda v: v["duplicates"], True),
            "risk": (lambda v: v["average_risk"] or 0, True),
            "last_seen": (lambda v: v["last_seen"], True),
        }
        key, largest_first = keys[sort]
        vendors.sort(key=key, reverse=largest_first)
        return {
            "total": total,
            "trusted": trusted_count,
            "matching": len(vendors),
            "vendors": vendors,
        }

    def get(self, vid: str) -> dict:
        """One vendor with its statistics, notes and trusted flag."""
        with self.engine.connect() as conn:
            return self._get(conn, vid)

    def summary(self, key: str) -> dict | None:
        """{id, name, trusted} for a vendor key, or None when the invoice has no supplier."""
        if not key:
            return None
        with self.engine.connect() as conn:
            for vendor in self._vendors(conn, key):
                return {"id": vendor["id"], "name": vendor["name"], "trusted": vendor["trusted"]}
        return None

    def invoices(self, vid: str, status=None, duplicates=False, limit=100) -> dict:
        """The vendor's recorded invoices, newest first, each with its review (if any)."""
        with self.engine.connect() as conn:
            vendor = self._get(conn, vid)
            conditions = [invoices.c.vendor_key == vendor["key"]]
            if status:
                conditions.append(invoices.c.validation_status == status)
            if duplicates:
                conditions.append(invoices.c.duplicate_kind.is_not(None))
            matching = conn.execute(
                select(func.count()).select_from(invoices).where(*conditions)
            ).scalar()
            rows = conn.execute(
                select(invoices, reviews.c.id.label("review_id"))
                .join(reviews, reviews.c.content_hash == invoices.c.content_hash, isouter=True)
                .where(*conditions)
                .order_by(invoices.c.id.desc())
                .limit(limit)
            ).all()
            return {
                "matching": matching,
                "invoices": [
                    {
                        "id": r.id,
                        "filename": r.filename,
                        "invoice_id": r.invoice_id,
                        "amount": r.amount_text,
                        "currency": r.currency,
                        "issue_date": r.issue_date,
                        "validation_status": r.validation_status,
                        "risk_score": r.risk_score,
                        "seen_at": r.seen_at,
                        "origin": r.origin,
                        "duplicate_kind": r.duplicate_kind,
                        "duplicate_of": r.duplicate_of,
                        "review_id": r.review_id,
                    }
                    for r in rows
                ],
            }

    def update(
        self, vid: str, actor: str, notes: str | None, trusted: bool | None
    ) -> tuple[dict, dict]:
        """
        Saves notes and/or the trusted flag (None leaves a value as it was) and returns
        (the vendor, what changed), where changed maps each field that really changed to
        its new value. Raises VendorNotFound for an unknown vendor.
        """
        with self.engine.begin() as conn:
            vendor = self._get(conn, vid)
            changed = {}
            if notes is not None and notes != vendor["notes"]:
                changed["notes"] = notes
            if trusted is not None and trusted != vendor["trusted"]:
                changed["trusted"] = trusted
            if changed:
                values = {**changed, "updated_at": _now(), "updated_by": actor}
                updated = conn.execute(
                    vendor_profiles.update()
                    .where(vendor_profiles.c.vendor_key == vendor["key"])
                    .values(**values)
                )
                if updated.rowcount == 0:
                    conn.execute(
                        vendor_profiles.insert().values(
                            vendor_key=vendor["key"],
                            **{"notes": "", "trusted": False, **values},
                        )
                    )
            return self._get(conn, vid), changed

    # Internals

    def _get(self, conn, vid: str) -> dict:
        for key in conn.execute(
            select(invoices.c.vendor_key).where(invoices.c.vendor_key != "").distinct()
        ).scalars():
            if vendor_id(key) == vid:
                return self._vendors(conn, key)[0]
        raise VendorNotFound(vid)

    @staticmethod
    def _vendors(conn, key: str | None = None) -> "list[dict]":
        """Statistics for every vendor (or just `key`), computed in the database."""

        def count_status(name):
            return func.sum(case((invoices.c.validation_status == name, 1), else_=0))

        query = (
            select(
                invoices.c.vendor_key,
                func.count().label("invoice_count"),
                *(count_status(name).label(name) for name in STATUSES),
                func.sum(case((invoices.c.duplicate_kind.is_not(None), 1), else_=0)).label(
                    "duplicates"
                ),
                func.avg(invoices.c.risk_score).label("average_risk"),
                func.min(invoices.c.seen_at).label("first_seen"),
                func.max(invoices.c.seen_at).label("last_seen"),
                func.max(invoices.c.id).label("last_id"),
            )
            .where(invoices.c.vendor_key != "")
            .group_by(invoices.c.vendor_key)
        )
        if key is not None:
            query = query.where(invoices.c.vendor_key == key)
        rows = conn.execute(query).all()
        # Amounts are added per currency: adding dollars to euros would mean nothing.
        money = {}
        amounts = (
            select(
                invoices.c.vendor_key,
                invoices.c.currency,
                func.sum(invoices.c.amount).label("total"),
                func.count(invoices.c.amount).label("n"),
            )
            .where(invoices.c.vendor_key != "", invoices.c.amount.is_not(None))
            .group_by(invoices.c.vendor_key, invoices.c.currency)
        )
        if key is not None:
            amounts = amounts.where(invoices.c.vendor_key == key)
        for row in conn.execute(amounts):
            money.setdefault(row.vendor_key, []).append(
                {
                    "currency": row.currency,
                    "total": round(row.total, 2),
                    "average": round(row.total / row.n, 2),
                    "count": row.n,
                }
            )
        profiles = {
            p.vendor_key: p
            for p in conn.execute(
                select(vendor_profiles).where(
                    vendor_profiles.c.vendor_key.in_([r.vendor_key for r in rows])
                )
            )
        }
        latest = {
            i.id: i
            for i in conn.execute(
                select(invoices.c.id, invoices.c.supplier_name, invoices.c.supplier_id).where(
                    invoices.c.id.in_([r.last_id for r in rows])
                )
            )
        }
        vendors = []
        for r in rows:
            last, profile = latest[r.last_id], profiles.get(r.vendor_key)
            # The currency with the most invoices is the headline; the rest are listed too.
            currencies = sorted(money.get(r.vendor_key, []), key=lambda c: -c["count"])
            main = currencies[0] if currencies else None
            vendors.append(
                {
                    "id": vendor_id(r.vendor_key),
                    "key": r.vendor_key,
                    "name": last.supplier_name or last.supplier_id,
                    "supplier_id": last.supplier_id,
                    "invoice_count": r.invoice_count,
                    "statuses": {name: int(getattr(r, name) or 0) for name in STATUSES},
                    "currency": main["currency"] if main else "",
                    "total_amount": main["total"] if main else 0.0,
                    "average_amount": main["average"] if main else None,
                    "currencies": currencies,
                    "duplicates": int(r.duplicates or 0),
                    "average_risk": round(r.average_risk, 1)
                    if r.average_risk is not None
                    else None,
                    "first_seen": r.first_seen,
                    "last_seen": r.last_seen,
                    "notes": profile.notes if profile else "",
                    "trusted": bool(profile.trusted) if profile else False,
                    "updated_by": profile.updated_by if profile else None,
                    "updated_at": profile.updated_at if profile else None,
                }
            )
        return vendors

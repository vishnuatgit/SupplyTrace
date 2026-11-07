"""
The tables, written with SQLAlchemy Core (plain tables, no ORM classes).

Timestamps are stored as ISO 8601 UTC text. That sorts correctly as text and
behaves the same on SQLite and PostgreSQL.
"""

from sqlalchemy import Column, Float, ForeignKey, Index, Integer, MetaData, String, Table, Text

metadata = MetaData()

# One row per invoice that needs a human. state and assignee change as people act;
# the full story lives in review_events.
reviews = Table(
    "reviews",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("content_hash", String(64), nullable=False, unique=True),  # SHA-256 of the file
    Column("filename", String(255), nullable=False),
    Column("invoice_id", String(255), nullable=False, default=""),  # the transaction ID, if found
    Column("amount", String(64), nullable=False, default=""),
    Column("validation_status", String(20), nullable=False),  # INVALID or REQUIRES_REVIEW
    Column("risk_score", Float),
    Column("reason", Text, nullable=False),  # why it is in the queue
    Column("state", String(10), nullable=False, default="open"),  # open, approved or rejected
    Column("assignee", String(60)),
    Column("created_at", String(32), nullable=False),
    Column("updated_at", String(32), nullable=False),
    # The analysis as it was produced (rule checklist, risk drivers), so the
    # detail page can show it without the XML, which is never stored.
    Column("result_json", Text, nullable=False),
    Index("ix_reviews_state", "state"),
)

# Append-only: rows are inserted and never updated or deleted.
review_events = Table(
    "review_events",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("review_id", Integer, ForeignKey("reviews.id"), nullable=False, index=True),
    Column("at", String(32), nullable=False),
    Column("actor", String(60), nullable=False),
    Column(
        "action", String(10), nullable=False
    ),  # created, assigned, commented, approved, rejected
    Column("comment", Text, nullable=False, default=""),
)

# One row per analysed invoice (every accepted check), with the fingerprint and
# key fields that duplicate detection compares, and the duplicate flag it got.
invoices = Table(
    "invoices",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("content_hash", String(64), nullable=False, index=True),  # SHA-256 of the file
    Column("filename", String(255), nullable=False),
    Column("invoice_id", String(255), nullable=False, default=""),  # the transaction ID
    Column("vendor_key", String(255), nullable=False, default="", index=True),
    Column("supplier_id", String(255), nullable=False, default=""),
    Column("supplier_name", String(255), nullable=False, default=""),
    Column("amount", Float),  # None unless the amount is a valid number
    Column("amount_text", String(64), nullable=False, default=""),
    Column("currency", String(16), nullable=False, default=""),
    Column("issue_date", String(10), nullable=False, default=""),  # YYYY-MM-DD, or empty
    Column("validation_status", String(20), nullable=False),
    Column("risk_score", Float),
    Column("origin", String(12), nullable=False),  # web, web-batch or demo
    Column("seen_at", String(32), nullable=False),
    Column("duplicate_kind", String(10)),  # exact, likely or None
    Column("duplicate_of", Integer),  # the earlier invoice's id
    Column("duplicate_reason", Text),
)

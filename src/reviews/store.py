"""
The review queue: invoices that need a person, who looks at them, and what they decided.

An invoice is in the queue because the rules said REQUIRES_REVIEW (added
automatically) or because someone sent an INVALID one. A review is open until a
reviewer approves or rejects it; after that it is closed and can only get comments.

Every action is also written to review_events as a new row. Events are never
changed or deleted, so the history of an invoice cannot be rewritten.
"""

import json
from datetime import UTC, datetime

from sqlalchemy import Engine, func, insert, or_, select, update

from src.storage.schema import review_events, reviews

OPEN, APPROVED, REJECTED = "open", "approved", "rejected"
STATES = (OPEN, APPROVED, REJECTED)

# Statuses that can be sent to the queue by hand. (A VALID invoice only gets there
# when it is flagged as a likely duplicate, which the server queues itself.)
QUEUEABLE = ("INVALID", "REQUIRES_REVIEW")

SYSTEM_ACTOR = "system"
ANONYMOUS = "anonymous"


class ReviewNotFound(Exception):
    """No review has this id (HTTP 404)."""


class ReviewStateError(Exception):
    """The action is not allowed in the review's current state (HTTP 409)."""


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _summary(row) -> dict:
    """A queue row: everything except the stored analysis."""
    return {
        "id": row.id,
        "filename": row.filename,
        "invoice_id": row.invoice_id,
        "amount": row.amount,
        "validation_status": row.validation_status,
        "risk_score": row.risk_score,
        "reason": row.reason,
        "state": row.state,
        "assignee": row.assignee,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
        # exact or likely, when the analysis found this invoice to be a duplicate
        "duplicate": (json.loads(row.result_json).get("duplicate") or {}).get("kind"),
    }


class ReviewStore:
    def __init__(self, engine: Engine):
        self.engine = engine

    # Adding to the queue

    def queue(self, result: dict, content_hash: str, reason: str, actor: str = SYSTEM_ACTOR):
        """
        Puts an analysed invoice in the queue and returns (review, created).
        An invoice (the same file content) is queued only once: if it has a review
        already, in any state, that review is returned and created is False.
        """
        now = _now()
        with self.engine.begin() as conn:
            existing = conn.execute(
                select(reviews.c.id).where(reviews.c.content_hash == content_hash)
            ).scalar()
            if existing is not None:
                return self._get(conn, existing), False
            score = result["prediction"]["risk_score"]
            review_id = conn.execute(
                insert(reviews).values(
                    content_hash=content_hash,
                    filename=result["filename"],
                    invoice_id=result["id"],
                    amount=result["fields"]["AMOUNT"]["value"],
                    validation_status=result["status"],
                    risk_score=score if isinstance(score, int | float) else None,
                    reason=reason,
                    state=OPEN,
                    created_at=now,
                    updated_at=now,
                    result_json=json.dumps(result, default=str),
                )
            ).inserted_primary_key[0]
            self._add_event(conn, review_id, now, actor, "created", reason)
            return self._get(conn, review_id), True

    # Reading

    def count(self) -> int:
        """How many reviews exist, in any state."""
        with self.engine.connect() as conn:
            return conn.execute(select(func.count()).select_from(reviews)).scalar()

    def find(self, content_hash: str) -> dict | None:
        """The review for this file content, or None if it was never queued."""
        with self.engine.connect() as conn:
            row = conn.execute(
                select(reviews).where(reviews.c.content_hash == content_hash)
            ).first()
            return _summary(row) if row else None

    def get(self, review_id: int) -> dict:
        """One review with its analysis and its history, oldest event first."""
        with self.engine.connect() as conn:
            return self._get(conn, review_id, detail=True)

    def list(self, state=None, assignee=None, status=None, q=None, limit=100) -> dict:
        """
        Reviews, newest first. assignee "unassigned" matches reviews with nobody
        assigned. `counts` is per state after the other filters, so the filter
        buttons can show how many each would give.
        """
        conditions = []
        if assignee == "unassigned":
            conditions.append(reviews.c.assignee.is_(None))
        elif assignee:
            conditions.append(func.lower(reviews.c.assignee) == assignee.lower())
        if status:
            conditions.append(reviews.c.validation_status == status)
        if q:
            pattern = f"%{q.lower()}%"
            conditions.append(
                or_(
                    func.lower(reviews.c.filename).like(pattern),
                    func.lower(reviews.c.invoice_id).like(pattern),
                )
            )
        with self.engine.connect() as conn:
            counts = dict.fromkeys(STATES, 0)
            for state_name, n in conn.execute(
                select(reviews.c.state, func.count()).where(*conditions).group_by(reviews.c.state)
            ):
                counts[state_name] = n
            query = select(reviews).where(*conditions)
            if state:
                query = query.where(reviews.c.state == state)
            rows = conn.execute(query.order_by(reviews.c.id.desc()).limit(limit)).all()
            assignees = conn.execute(
                select(reviews.c.assignee).where(reviews.c.assignee.is_not(None)).distinct()
            ).scalars()
            return {
                "counts": counts,
                "matching": counts[state] if state else sum(counts.values()),
                "reviews": [_summary(row) for row in rows],
                "assignees": sorted(assignees, key=str.lower),
            }

    # Acting on a review

    def assign(self, review_id: int, reviewer: str, actor: str) -> dict:
        """Assigns (or reassigns) an open review to a reviewer."""
        return self._act(review_id, actor, "assigned", f"Assigned to {reviewer}", assignee=reviewer)

    def comment(self, review_id: int, actor: str, comment: str) -> dict:
        """Adds a comment. Allowed in any state; it does not change the review."""
        return self._act(review_id, actor, "commented", comment, needs_open=False)

    def approve(self, review_id: int, actor: str, comment: str) -> dict:
        return self._act(review_id, actor, "approved", comment, state=APPROVED)

    def reject(self, review_id: int, actor: str, comment: str) -> dict:
        return self._act(review_id, actor, "rejected", comment, state=REJECTED)

    def _act(self, review_id, actor, action, comment, needs_open=True, **changes) -> dict:
        """
        The one place a review changes. It checks that the comment is not blank,
        that the review exists and (for most actions) is still open, then updates
        the review and appends the event in a single transaction, so the row and
        its history never disagree.
        """
        if not comment.strip():
            raise ValueError("A comment is required")
        now = _now()
        with self.engine.begin() as conn:
            row = conn.execute(select(reviews).where(reviews.c.id == review_id)).first()
            if row is None:
                raise ReviewNotFound(review_id)
            if needs_open and row.state != OPEN:
                raise ReviewStateError(f"Review {review_id} is already {row.state}")
            conn.execute(
                update(reviews).where(reviews.c.id == review_id).values(updated_at=now, **changes)
            )
            self._add_event(conn, review_id, now, actor, action, comment)
            return self._get(conn, review_id, detail=True)

    # Internals

    @staticmethod
    def _add_event(conn, review_id, at, actor, action, comment):
        conn.execute(
            insert(review_events).values(
                review_id=review_id, at=at, actor=actor, action=action, comment=comment
            )
        )

    @staticmethod
    def _get(conn, review_id, detail=False) -> dict:
        row = conn.execute(select(reviews).where(reviews.c.id == review_id)).first()
        if row is None:
            raise ReviewNotFound(review_id)
        review = _summary(row)
        if detail:
            events = conn.execute(
                select(review_events)
                .where(review_events.c.review_id == review_id)
                .order_by(review_events.c.id)
            ).all()
            review["result"] = json.loads(row.result_json)
            review["history"] = [
                {"at": e.at, "actor": e.actor, "action": e.action, "comment": e.comment}
                for e in events
            ]
        return review

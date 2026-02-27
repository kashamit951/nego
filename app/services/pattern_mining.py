from sqlalchemy import and_, case, func, select
from sqlalchemy.orm import Session

from app.db.models import NegotiationOutcome


class PatternMiningService:
    def rejection_alert(
        self,
        db: Session,
        tenant_id: str,
        clause_type: str,
        client_id: str | None = None,
        min_samples: int = 10,
        rejection_threshold: float = 0.8,
    ) -> str | None:
        base_filter = [
            NegotiationOutcome.tenant_id == tenant_id,
            NegotiationOutcome.clause_type == clause_type,
        ]
        if client_id:
            base_filter.append(NegotiationOutcome.client_id == client_id)

        row = db.execute(
            select(
                func.count(NegotiationOutcome.id),
                func.sum(case((NegotiationOutcome.outcome == "rejected", 1), else_=0)),
            ).where(and_(*base_filter))
        ).one()

        total = int(row[0] or 0)
        rejected = int(row[1] or 0)
        if total < min_samples:
            return None
        ratio = rejected / total
        if ratio >= rejection_threshold:
            pct = round(ratio * 100)
            scope_label = f"client {client_id}" if client_id else "all clients in tenant"
            return (
                f"High rejection pattern detected: {pct}% of {clause_type} clauses were rejected "
                f"historically for {scope_label}."
            )
        return None

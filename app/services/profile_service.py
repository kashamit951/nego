import re

from sqlalchemy import and_, case, func, select
from sqlalchemy.orm import Session

from app.db.models import NegotiationOutcome


class ProfileService:
    def client_profile(
        self,
        db: Session,
        tenant_id: str,
        client_id: str | None = None,
    ) -> dict:
        base_filter = [NegotiationOutcome.tenant_id == tenant_id]
        if client_id:
            base_filter.append(NegotiationOutcome.client_id == client_id)

        rows = db.execute(
            select(
                func.count(NegotiationOutcome.id),
                func.avg(NegotiationOutcome.negotiation_rounds),
                func.sum(case((NegotiationOutcome.outcome == "rejected", 1), else_=0)),
            ).where(and_(*base_filter))
        ).one()

        total = int(rows[0] or 0)
        avg_rounds = float(rows[1] or 0)

        liability_texts = db.execute(
            select(NegotiationOutcome.final_text).where(
                and_(
                    *base_filter,
                    NegotiationOutcome.clause_type == "limitation_of_liability",
                    NegotiationOutcome.final_text.is_not(None),
                )
            )
        ).scalars().all()

        cap_values = []
        for text in liability_texts:
            if not text:
                continue
            match = re.search(r"(\d+(?:\.\d+)?)x\s+annual\s+fees", text.lower())
            if match:
                cap_values.append(match.group(1) + "x annual fees")

        preference = cap_values[0] if cap_values else "1x annual fees"
        return {
            "sample_size": total,
            "client_id": client_id,
            "avg_negotiation_rounds": round(avg_rounds, 2),
            "liability_cap_preference": preference,
            "rejects_unlimited_liability": True,
            "prefers_mutual_indemnity": True,
        }

    def counterparty_profile(
        self,
        db: Session,
        tenant_id: str,
        counterparty_name: str | None,
        client_id: str | None = None,
    ) -> dict:
        if not counterparty_name:
            return {"sample_size": 0}

        base_filter = [
            NegotiationOutcome.tenant_id == tenant_id,
            NegotiationOutcome.counterparty_name == counterparty_name,
        ]
        if client_id:
            base_filter.append(NegotiationOutcome.client_id == client_id)

        rows = db.execute(
            select(
                func.count(NegotiationOutcome.id),
                func.sum(
                    case(
                        (NegotiationOutcome.counterparty_edit.ilike("%unlimited%liability%"), 1),
                        else_=0,
                    )
                ),
                func.sum(
                    case((NegotiationOutcome.final_text.ilike("%1.5x%"), 1), else_=0)
                ),
                func.sum(
                    case(
                        (NegotiationOutcome.original_text.ilike("%consequential damages%"), 1),
                        else_=0,
                    )
                ),
            ).where(and_(*base_filter))
        ).one()

        total = int(rows[0] or 0)
        if total == 0:
            return {"sample_size": 0}

        return {
            "sample_size": total,
            "client_id": client_id,
            "pushes_unlimited_liability_ratio": round(float(rows[1] or 0) / total, 2),
            "accepts_1_5x_cap_ratio": round(float(rows[2] or 0) / total, 2),
            "consequential_damages_mentions_ratio": round(float(rows[3] or 0) / total, 2),
        }

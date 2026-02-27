from sqlalchemy import and_, select

from app.db.models import NegotiationOutcome
from app.schemas.contracts import StrategicSuggestionRequest
from app.services.llm_provider import LLMProvider
from app.services.profile_service import ProfileService
from app.services.retrieval import SmartRetrievalService


class StrategySuggestionService:
    def __init__(
        self,
        retrieval_service: SmartRetrievalService,
        profile_service: ProfileService,
        llm_provider: LLMProvider,
    ) -> None:
        self.retrieval_service = retrieval_service
        self.profile_service = profile_service
        self.llm_provider = llm_provider

    def suggest(self, db, tenant_id: str, request: StrategicSuggestionRequest) -> dict:
        retrieval = self.retrieval_service.retrieve(db, tenant_id, request)
        clause_type = retrieval["clause_type"]
        examples = retrieval["examples"]
        client_filter = retrieval.get("client_id")
        analysis_scope = retrieval.get("analysis_scope", request.analysis_scope)
        example_source = retrieval.get("example_source", request.example_source)

        historical_pattern = self._historical_negotiation_pattern(
            db=db,
            tenant_id=tenant_id,
            clause_type=clause_type,
            client_id=client_filter,
            doc_type=request.doc_type,
            counterparty_name=request.counterparty_name,
        )
        client_profile = self.profile_service.client_profile(db, tenant_id, client_id=client_filter)
        counterparty_profile = self.profile_service.counterparty_profile(
            db, tenant_id, request.counterparty_name, client_id=client_filter
        )

        draft_candidates = []
        for temperature in (0.15, 0.35, 0.55):
            candidate = self.llm_provider.suggest(
                clause_type=clause_type,
                new_clause_text=request.new_clause_text,
                client_profile=client_profile,
                counterparty_profile=counterparty_profile,
                examples=examples,
                temperature=temperature,
            )
            verification = self.llm_provider.verify(
                clause_type=clause_type,
                new_clause_text=request.new_clause_text,
                examples=examples,
                candidate=candidate,
                temperature=0.0,
            )
            draft_candidates.append({"candidate": candidate, "verification": verification})

        selected = self._choose_consensus_candidate(draft_candidates)
        if not selected:
            return self._abstained_response(
                clause_type=clause_type,
                analysis_scope=analysis_scope,
                client_id=client_filter,
                example_source=example_source,
                historical_pattern=historical_pattern,
                examples=examples,
            )

        candidate = selected["candidate"]
        verification = selected["verification"]
        proposed_redline = verification.get("corrected_proposed_redline") or candidate["proposed_redline"]
        fallback_position = verification.get("corrected_fallback_position") or candidate["fallback_position"]
        verification_summary = verification.get("verification_summary") or "Output is evidence-grounded."
        scope_text = f"single client {client_filter}" if client_filter else "all clients within tenant"
        explanation = (
            f"Prediction scope is {scope_text}. "
            f"LLM consensus selected from {len(draft_candidates)} drafts with verifier support "
            f"{round(float(verification.get('support_score') or 0.0), 4)}. "
            f"{candidate['business_explanation']} "
            f"Verifier note: {verification_summary}"
        )

        return {
            "clause_type": clause_type,
            "analysis_scope": analysis_scope,
            "client_id": client_filter,
            "example_source": example_source,
            "risk_score": round(float(candidate["risk_score"]), 4),
            "acceptance_probability": round(float(candidate["acceptance_probability"]), 4),
            "proposed_redline": proposed_redline,
            "business_explanation": explanation,
            "fallback_position": fallback_position,
            "pattern_alert": candidate.get("pattern_alert"),
            "predicted_final_outcome": candidate["predicted_final_outcome"],
            "historical_pattern": historical_pattern,
            "close_time_estimate": {
                "expected_rounds_remaining": round(float(candidate["expected_rounds_remaining"]), 2),
                "expected_days_to_close": int(candidate["expected_days_to_close"]),
                "probability_close_in_7_days": round(float(candidate["probability_close_in_7_days"]), 4),
                "sample_size": int(historical_pattern.get("sample_size", 0)),
                "confidence": round(
                    float(min(1.0, max(0.0, (candidate["confidence"] + verification["confidence"]) / 2.0))), 4
                ),
                "fastest_path_hint": candidate["fastest_path_hint"],
            },
            "retrieved_examples": examples,
        }

    @staticmethod
    def _choose_consensus_candidate(drafts: list[dict]) -> dict | None:
        supported = [row for row in drafts if row["verification"].get("supported")]
        if not supported:
            return None
        supported.sort(
            key=lambda row: (
                float(row["verification"].get("support_score") or 0.0),
                float(row["verification"].get("confidence") or 0.0),
                float(row["candidate"].get("confidence") or 0.0),
            ),
            reverse=True,
        )
        best = supported[0]
        if float(best["verification"].get("support_score") or 0.0) < 0.4:
            return None
        return best

    @staticmethod
    def _abstained_response(
        *,
        clause_type: str,
        analysis_scope: str,
        client_id: str | None,
        example_source: str,
        historical_pattern: dict,
        examples: list[dict],
    ) -> dict:
        return {
            "clause_type": clause_type,
            "analysis_scope": analysis_scope,
            "client_id": client_id,
            "example_source": example_source,
            "risk_score": 0.5,
            "acceptance_probability": 0.0,
            "proposed_redline": "INSUFFICIENT_EVIDENCE",
            "business_explanation": (
                "The LLM verifier rejected all drafts due to weak evidence support. "
                "Provide more relevant precedent examples before proposing language."
            ),
            "fallback_position": "Ask counterparty for rationale and narrow the clause scope before redrafting.",
            "pattern_alert": "Abstained due to insufficient evidence-grounded confidence.",
            "predicted_final_outcome": "partially_accepted",
            "historical_pattern": historical_pattern,
            "close_time_estimate": {
                "expected_rounds_remaining": 0.0,
                "expected_days_to_close": 7,
                "probability_close_in_7_days": 0.0,
                "sample_size": int(historical_pattern.get("sample_size", 0)),
                "confidence": 0.0,
                "fastest_path_hint": "Ingest more domain-specific negotiated clauses to improve evidence support.",
            },
            "retrieved_examples": examples,
        }

    @staticmethod
    def _historical_negotiation_pattern(
        *,
        db,
        tenant_id: str,
        clause_type: str,
        client_id: str | None,
        doc_type: str | None,
        counterparty_name: str | None,
    ) -> dict:
        filters = [
            NegotiationOutcome.tenant_id == tenant_id,
            NegotiationOutcome.clause_type == clause_type,
        ]
        if client_id:
            filters.append(NegotiationOutcome.client_id == client_id)
        if doc_type:
            filters.append(NegotiationOutcome.doc_type == doc_type)
        if counterparty_name:
            filters.append(NegotiationOutcome.counterparty_name == counterparty_name)

        rows = db.execute(
            select(
                NegotiationOutcome.outcome,
                NegotiationOutcome.negotiation_rounds,
                NegotiationOutcome.redline_events,
            ).where(and_(*filters)).limit(500)
        ).all()

        sample_size = len(rows)
        if sample_size == 0:
            return {
                "sample_size": 0,
                "avg_rounds": 0.0,
                "avg_redline_events": 0.0,
                "accepted_rate": 0.0,
                "partially_accepted_rate": 0.0,
                "rejected_rate": 0.0,
                "dominant_redline_type": None,
                "negotiation_style_hint": "No prior negotiation history found for this scope.",
            }

        accepted = 0
        partial = 0
        rejected = 0
        rounds_total = 0.0
        event_total = 0.0
        redline_types: dict[str, int] = {}
        for item in rows:
            rounds_total += float(max(1, int(item.negotiation_rounds or 1)))
            events = item.redline_events if isinstance(item.redline_events, list) else []
            event_total += float(len(events))
            for event in events:
                event_type = str((event or {}).get("type") or "other")
                redline_types[event_type] = redline_types.get(event_type, 0) + 1

            if item.outcome == "accepted":
                accepted += 1
            elif item.outcome == "rejected":
                rejected += 1
            else:
                partial += 1

        accepted_rate = accepted / sample_size
        partial_rate = partial / sample_size
        rejected_rate = rejected / sample_size
        avg_rounds = rounds_total / sample_size
        avg_events = event_total / sample_size
        dominant_redline_type = max(redline_types.items(), key=lambda kv: kv[1])[0] if redline_types else None

        return {
            "sample_size": sample_size,
            "avg_rounds": round(avg_rounds, 2),
            "avg_redline_events": round(avg_events, 2),
            "accepted_rate": round(accepted_rate, 4),
            "partially_accepted_rate": round(partial_rate, 4),
            "rejected_rate": round(rejected_rate, 4),
            "dominant_redline_type": dominant_redline_type,
            "negotiation_style_hint": "Descriptive historical summary provided for LLM evidence context.",
        }

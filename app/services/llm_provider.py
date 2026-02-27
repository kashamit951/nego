import json
import logging
import re
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class LLMProvider:
    def suggest(
        self,
        *,
        clause_type: str,
        new_clause_text: str,
        client_profile: dict,
        counterparty_profile: dict,
        examples: list[dict],
        temperature: float = 0.2,
    ) -> dict:
        raise NotImplementedError

    def verify(
        self,
        *,
        clause_type: str,
        new_clause_text: str,
        examples: list[dict],
        candidate: dict,
        temperature: float = 0.0,
    ) -> dict:
        raise NotImplementedError

    def plan_negotiation_flow(
        self,
        *,
        doc_type: str,
        analysis_scope: str,
        signals: list[dict],
        retrieved_examples: list[dict],
    ) -> dict:
        raise NotImplementedError

    def classify_comment_signal(self, *, comment_text: str, profile: str) -> dict:
        raise NotImplementedError

    def rewrite_signal_delta(
        self,
        *,
        source_type: str,
        incoming_text: str,
        precedent: dict,
        max_redline_words: int,
        max_comment_words: int,
        strict_wording: bool = False,
    ) -> dict:
        raise NotImplementedError


class OpenAICompatibleLLMProvider(LLMProvider):
    def __init__(self, api_base: str, api_key: str | None, model: str, timeout_seconds: float) -> None:
        self.api_base = api_base.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds

    def suggest(
        self,
        *,
        clause_type: str,
        new_clause_text: str,
        client_profile: dict,
        counterparty_profile: dict,
        examples: list[dict],
        temperature: float = 0.2,
    ) -> dict:
        prompt = self._suggest_prompt(
            clause_type=clause_type,
            new_clause_text=new_clause_text,
            client_profile=client_profile,
            counterparty_profile=counterparty_profile,
            examples=examples,
        )
        parsed = self._chat_json(
            system_prompt=(
                "You are a senior legal negotiator. "
                "Use only supplied evidence and return strict JSON."
            ),
            user_prompt=prompt,
            temperature=temperature,
        )
        predicted_outcome = str(parsed.get("predicted_final_outcome") or "partially_accepted").strip().lower()
        if predicted_outcome not in {"accepted", "rejected", "partially_accepted"}:
            predicted_outcome = "partially_accepted"
        return {
            "proposed_redline": str(parsed.get("proposed_redline") or new_clause_text),
            "business_explanation": str(
                parsed.get("business_explanation")
                or "Generated from retrieved negotiation evidence."
            ),
            "fallback_position": str(
                parsed.get("fallback_position")
                or "Keep wording narrow and request reciprocal obligations."
            ),
            "risk_score": self._clamp_01(parsed.get("risk_score"), default=0.5),
            "acceptance_probability": self._clamp_01(parsed.get("acceptance_probability"), default=0.5),
            "predicted_final_outcome": predicted_outcome,
            "expected_rounds_remaining": self._clamp_float(parsed.get("expected_rounds_remaining"), 0.0, 10.0, 2.0),
            "expected_days_to_close": int(self._clamp_float(parsed.get("expected_days_to_close"), 1.0, 60.0, 7.0)),
            "probability_close_in_7_days": self._clamp_01(parsed.get("probability_close_in_7_days"), default=0.5),
            "confidence": self._clamp_01(parsed.get("confidence"), default=0.5),
            "fastest_path_hint": str(parsed.get("fastest_path_hint") or "Use precedent-aligned language first."),
            "pattern_alert": str(parsed.get("pattern_alert") or "").strip() or None,
        }

    def verify(
        self,
        *,
        clause_type: str,
        new_clause_text: str,
        examples: list[dict],
        candidate: dict,
        temperature: float = 0.0,
    ) -> dict:
        parsed = self._chat_json(
            system_prompt=(
                "You are a strict legal QA verifier. "
                "Approve only claims grounded in supplied evidence."
            ),
            user_prompt=self._verify_prompt(
                clause_type=clause_type,
                new_clause_text=new_clause_text,
                examples=examples,
                candidate=candidate,
            ),
            temperature=temperature,
        )
        return {
            "supported": bool(parsed.get("supported", False)),
            "support_score": self._clamp_01(parsed.get("support_score"), default=0.0),
            "issues": [str(x) for x in (parsed.get("issues") or [])][:5],
            "corrected_proposed_redline": str(parsed.get("corrected_proposed_redline") or "").strip() or None,
            "corrected_fallback_position": str(parsed.get("corrected_fallback_position") or "").strip() or None,
            "confidence": self._clamp_01(parsed.get("confidence"), default=0.5),
            "verification_summary": str(parsed.get("verification_summary") or "").strip(),
        }

    def plan_negotiation_flow(
        self,
        *,
        doc_type: str,
        analysis_scope: str,
        signals: list[dict],
        retrieved_examples: list[dict],
    ) -> dict:
        parsed = self._chat_json(
            system_prompt=(
                "You are a legal negotiation strategist focused on reducing back-and-forth cycles. "
                "Use only supplied corpus signals and examples."
            ),
            user_prompt=self._negotiation_playbook_prompt(
                doc_type=doc_type,
                analysis_scope=analysis_scope,
                signals=signals,
                retrieved_examples=retrieved_examples,
            ),
            temperature=0.2,
        )
        return {
            "playbook_summary": str(parsed.get("playbook_summary") or "Use precedent-backed redlines and concise comments."),
            "fastest_path_hint": str(parsed.get("fastest_path_hint") or "Send one primary and one fallback position."),
            "expected_rounds_remaining": self._clamp_float(parsed.get("expected_rounds_remaining"), 0.0, 12.0, 2.0),
            "expected_days_to_close": int(self._clamp_float(parsed.get("expected_days_to_close"), 1.0, 60.0, 7.0)),
            "probability_close_in_7_days": self._clamp_01(parsed.get("probability_close_in_7_days"), default=0.5),
            "confidence": self._clamp_01(parsed.get("confidence"), default=0.5),
            "items": parsed.get("items") if isinstance(parsed.get("items"), list) else [],
        }

    def classify_comment_signal(self, *, comment_text: str, profile: str) -> dict:
        parsed = self._chat_json(
            system_prompt=(
                "You classify legal negotiation comments for outcome learning. "
                "Return strict JSON."
            ),
            user_prompt=(
                "Return strict JSON with keys: signal, confidence, rationale.\n"
                "signal must be one of: accept, reject, revise, neutral.\n"
                f"profile={profile}\n"
                f"comment_text={comment_text[:1200]}\n"
            ),
            temperature=0.0,
        )
        signal = str(parsed.get("signal") or "neutral").strip().lower()
        if signal not in {"accept", "reject", "revise", "neutral"}:
            signal = "neutral"
        return {
            "signal": signal,
            "confidence": self._clamp_01(parsed.get("confidence"), default=0.5),
            "rationale": str(parsed.get("rationale") or "").strip(),
        }

    def rewrite_signal_delta(
        self,
        *,
        source_type: str,
        incoming_text: str,
        precedent: dict,
        max_redline_words: int,
        max_comment_words: int,
        strict_wording: bool = False,
    ) -> dict:
        strict_block = (
            "Use real contractual wording only; do not output guidance like "
            "'remove', 'revise', 'make flexible', or placeholders.\n"
            "Output the exact replacement wording someone can paste into redline."
            if strict_wording
            else ""
        )
        parsed = self._chat_json(
            system_prompt=(
                "You rewrite legal negotiation signals into concise delta edits only. "
                "Never echo incoming text unchanged."
            ),
            user_prompt=(
                "Return strict JSON with keys: suggested_redline, suggested_comment.\n"
                "Hard constraints:\n"
                f"- suggested_redline must differ from incoming_text and be <= {max_redline_words} words.\n"
                f"- suggested_comment must be <= {max_comment_words} words and explicitly reference the redline intent.\n"
                "- Keep scope narrow; do not add long agreement boilerplate.\n"
                f"{strict_block}\n"
                f"source_type={source_type}\n"
                f"incoming_text={incoming_text}\n"
                f"precedent={json.dumps(precedent)}\n"
            ),
            temperature=0.1,
        )
        return {
            "suggested_redline": str(parsed.get("suggested_redline") or "").strip(),
            "suggested_comment": str(parsed.get("suggested_comment") or "").strip(),
        }

    @staticmethod
    def _parse_json_content(content: Any) -> dict[str, Any]:
        if isinstance(content, dict):
            return content

        text = str(content or "").strip()
        if not text:
            raise ValueError("empty LLM response content")

        # Strip markdown fences if present.
        if text.startswith("```"):
            text = re.sub(r"^```[a-zA-Z0-9]*\s*", "", text)
            text = re.sub(r"\s*```$", "", text)

        # Attempt direct parse first.
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass

        # Try extracting the first JSON object block from mixed text.
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            candidate = text[start : end + 1]
            # Remove control chars that break JSON parsing.
            candidate = re.sub(r"[\x00-\x08\x0B\x0C\x0E-\x1F]", " ", candidate)
            candidate = candidate.replace("\r", " ").replace("\n", " ")
            try:
                parsed = json.loads(candidate)
                if isinstance(parsed, dict):
                    return parsed
            except Exception:
                pass

        # Best-effort key extraction from non-JSON outputs.
        extracted: dict[str, Any] = {}
        for key in ("proposed_redline", "business_explanation", "fallback_position"):
            pattern = rf'"?{key}"?\s*[:=]\s*"?(.*?)"?(?=,\s*"?[a-zA-Z_]+"?\s*[:=]|$)'
            match = re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL)
            if match:
                extracted[key] = re.sub(r"\s+", " ", match.group(1)).strip().strip('"')

        if extracted:
            return extracted

        raise ValueError("LLM response was not valid JSON and could not be repaired")

    @staticmethod
    def _prompt(
        *,
        clause_type: str,
        new_clause_text: str,
        client_profile: dict,
        counterparty_profile: dict,
        examples: list[dict],
    ) -> str:
        return OpenAICompatibleLLMProvider._suggest_prompt(
            clause_type=clause_type,
            new_clause_text=new_clause_text,
            client_profile=client_profile,
            counterparty_profile=counterparty_profile,
            examples=examples,
        )

    @staticmethod
    def _suggest_prompt(
        *,
        clause_type: str,
        new_clause_text: str,
        client_profile: dict,
        counterparty_profile: dict,
        examples: list[dict],
    ) -> str:
        top_examples = examples[:3]
        example_block = "\n".join(
            [
                f"- outcome={ex.get('outcome')} counterparty={ex.get('counterparty_name')} text={ex.get('clause_text')}"
                for ex in top_examples
            ]
        )
        return (
            "Return strict JSON with keys:\n"
            "proposed_redline, business_explanation, fallback_position,\n"
            "risk_score, acceptance_probability, predicted_final_outcome,\n"
            "expected_rounds_remaining, expected_days_to_close, probability_close_in_7_days,\n"
            "confidence, fastest_path_hint, pattern_alert.\n"
            "Do not invent facts outside examples.\n"
            f"Clause type: {clause_type}\n"
            f"New clause: {new_clause_text}\n"
            f"Client profile: {json.dumps(client_profile)}\n"
            f"Counterparty profile: {json.dumps(counterparty_profile)}\n"
            f"Past examples:\n{example_block}\n"
        )

    @staticmethod
    def _verify_prompt(
        *,
        clause_type: str,
        new_clause_text: str,
        examples: list[dict],
        candidate: dict,
    ) -> str:
        top_examples = examples[:6]
        example_block = "\n".join(
            [
                f"- outcome={ex.get('outcome')} counterparty={ex.get('counterparty_name')} text={ex.get('clause_text')}"
                for ex in top_examples
            ]
        )
        return (
            "Return strict JSON with keys:\n"
            "supported, support_score, issues, corrected_proposed_redline,\n"
            "corrected_fallback_position, confidence, verification_summary.\n"
            "Set supported=false if candidate claims are weakly supported by evidence.\n"
            f"Clause type: {clause_type}\n"
            f"Incoming clause: {new_clause_text}\n"
            f"Candidate JSON: {json.dumps(candidate)}\n"
            f"Evidence examples:\n{example_block}\n"
        )

    @staticmethod
    def _negotiation_playbook_prompt(
        *,
        doc_type: str,
        analysis_scope: str,
        signals: list[dict],
        retrieved_examples: list[dict],
    ) -> str:
        return (
            "Return strict JSON with keys:\n"
            "playbook_summary, fastest_path_hint, expected_rounds_remaining,\n"
            "expected_days_to_close, probability_close_in_7_days, confidence, items.\n"
            "items must be an array of objects with keys:\n"
            "source_type, source_index, incoming_text, suggested_redline, suggested_comment,\n"
            "rationale, expected_outcome, confidence.\n"
            "Do not copy incoming_text verbatim as suggested_redline unless evidence proves that exact text closed successfully.\n"
            "Use example_outcome/example_final_text/example_client_response to explain how similar negotiations ended.\n"
            "Suggested_comment must be specific to the redline and include resolution intent.\n"
            "Doc type: "
            f"{doc_type}\n"
            f"Analysis scope: {analysis_scope}\n"
            f"Incoming signals: {json.dumps(signals)}\n"
            f"Retrieved examples: {json.dumps(retrieved_examples[:40])}\n"
        )

    def _chat_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        temperature: float,
    ) -> dict[str, Any]:
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": max(0.0, min(1.0, float(temperature))),
            "response_format": {"type": "json_object"},
        }

        with httpx.Client(timeout=self.timeout_seconds) as client:
            response = client.post(f"{self.api_base}/chat/completions", headers=headers, json=payload)
            response.raise_for_status()
            body = response.json()

        content = body["choices"][0]["message"]["content"]
        return self._parse_json_content(content)

    @staticmethod
    def _clamp_float(value: Any, lower: float, upper: float, default: float) -> float:
        try:
            parsed = float(value)
        except Exception:
            parsed = default
        return max(lower, min(upper, parsed))

    @staticmethod
    def _clamp_01(value: Any, default: float) -> float:
        return OpenAICompatibleLLMProvider._clamp_float(value, 0.0, 1.0, default)


class FallbackLLMProvider(LLMProvider):
    def __init__(self, primary: LLMProvider, fallback: LLMProvider) -> None:
        self.primary = primary
        self.fallback = fallback

    def suggest(
        self,
        *,
        clause_type: str,
        new_clause_text: str,
        client_profile: dict,
        counterparty_profile: dict,
        examples: list[dict],
    ) -> dict:
        try:
            return self.primary.suggest(
                clause_type=clause_type,
                new_clause_text=new_clause_text,
                client_profile=client_profile,
                counterparty_profile=counterparty_profile,
                examples=examples,
            )
        except Exception as exc:
            logger.warning("primary LLM provider failed (%s), using fallback", exc)
            return self.fallback.suggest(
                clause_type=clause_type,
                new_clause_text=new_clause_text,
                client_profile=client_profile,
                counterparty_profile=counterparty_profile,
                examples=examples,
            )


def build_llm_provider(settings) -> LLMProvider:
    provider_name = settings.llm_provider.lower()

    if provider_name == "openai_compatible" and settings.llm_api_base:
        return OpenAICompatibleLLMProvider(
            api_base=settings.llm_api_base,
            api_key=settings.llm_api_key,
            model=settings.llm_model,
            timeout_seconds=settings.llm_timeout_seconds,
        )

    raise ValueError("Set NEGO_LLM_PROVIDER=openai_compatible and NEGO_LLM_API_BASE for LLM-only operation.")

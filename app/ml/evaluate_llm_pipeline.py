import argparse
import json
from pathlib import Path


def _safe_float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def evaluate_cases(cases: list[dict]) -> dict:
    total = len(cases)
    if total == 0:
        return {
            "total_cases": 0,
            "outcome_accuracy": 0.0,
            "redline_phrase_accuracy": 0.0,
            "abstain_rate": 0.0,
            "hallucination_proxy_rate": 0.0,
        }

    correct_outcome = 0
    correct_redline_phrase = 0
    abstained = 0
    hallucination_proxy = 0
    phrase_cases = 0

    for case in cases:
        expected_outcome = str(case.get("expected_outcome") or "").strip().lower()
        actual_outcome = str(case.get("actual_outcome") or "").strip().lower()
        if expected_outcome and actual_outcome == expected_outcome:
            correct_outcome += 1

        required_phrases = [str(x).strip().lower() for x in (case.get("expected_redline_contains") or []) if str(x).strip()]
        actual_redline = str(case.get("actual_proposed_redline") or "").strip().lower()
        if required_phrases:
            phrase_cases += 1
            if all(phrase in actual_redline for phrase in required_phrases):
                correct_redline_phrase += 1

        is_abstained = bool(case.get("abstained", False))
        if is_abstained:
            abstained += 1

        # Proxy: if model did not abstain and confidence is low, count as potential hallucination risk.
        confidence = _safe_float(case.get("confidence"), default=0.0)
        if (not is_abstained) and confidence < 0.35:
            hallucination_proxy += 1

    return {
        "total_cases": total,
        "outcome_accuracy": round(correct_outcome / total, 4),
        "redline_phrase_accuracy": round((correct_redline_phrase / phrase_cases), 4) if phrase_cases else 0.0,
        "abstain_rate": round(abstained / total, 4),
        "hallucination_proxy_rate": round(hallucination_proxy / total, 4),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate LLM strategy outputs from labeled JSON cases.")
    parser.add_argument("--cases", required=True, help="Path to JSON file containing a list of labeled cases.")
    args = parser.parse_args()

    case_path = Path(args.cases)
    if not case_path.exists():
        raise SystemExit(f"Cases file not found: {case_path}")

    content = json.loads(case_path.read_text(encoding="utf-8"))
    if not isinstance(content, list):
        raise SystemExit("Cases JSON must be a list.")

    results = evaluate_cases(content)
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()

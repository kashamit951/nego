import logging
import math
from dataclasses import dataclass

import numpy as np

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class AcceptanceFeatures:
    semantic_similarity: float
    same_counterparty: float
    similar_outcome: float
    similar_contract_value: float
    clause_type_confidence: float

    def as_vector(self) -> list[float]:
        return [
            self.semantic_similarity,
            self.same_counterparty,
            self.similar_outcome,
            self.similar_contract_value,
            self.clause_type_confidence,
        ]


class AcceptanceProbabilityModel:
    def predict(self, features: AcceptanceFeatures) -> float:
        raise NotImplementedError


class BaselineAcceptanceProbabilityModel(AcceptanceProbabilityModel):
    """Deterministic logistic baseline if trained artifacts are unavailable."""

    def predict(self, features: AcceptanceFeatures) -> float:
        z = (
            -0.25
            + 1.4 * features.semantic_similarity
            + 0.5 * features.same_counterparty
            + 0.7 * features.similar_outcome
            + 0.35 * features.similar_contract_value
            + 0.4 * features.clause_type_confidence
        )
        return 1 / (1 + math.exp(-z))


class XGBoostAcceptanceModel(AcceptanceProbabilityModel):
    def __init__(self, artifact_path: str) -> None:
        import xgboost as xgb

        self.xgb = xgb
        self.model = xgb.Booster()
        self.model.load_model(artifact_path)

    def predict(self, features: AcceptanceFeatures) -> float:
        dmatrix = self.xgb.DMatrix(np.asarray([features.as_vector()], dtype=np.float32))
        pred = float(self.model.predict(dmatrix)[0])
        return max(0.0, min(1.0, pred))


class SklearnAcceptanceModel(AcceptanceProbabilityModel):
    def __init__(self, artifact_path: str) -> None:
        import joblib

        self.model = joblib.load(artifact_path)

    def predict(self, features: AcceptanceFeatures) -> float:
        vector = np.asarray([features.as_vector()], dtype=np.float32)
        if hasattr(self.model, "predict_proba"):
            probs = self.model.predict_proba(vector)[0]
            classes = list(getattr(self.model, "classes_", [0, 1]))
            if 1 in classes:
                idx = classes.index(1)
            elif "accepted" in classes:
                idx = classes.index("accepted")
            else:
                idx = min(1, len(classes) - 1)
            pred = float(probs[idx])
            return max(0.0, min(1.0, pred))

        label = float(self.model.predict(vector)[0])
        return 1.0 if label >= 1 else 0.0


def build_acceptance_model(settings) -> AcceptanceProbabilityModel:
    provider = settings.acceptance_model_provider.lower()
    artifact_path = settings.acceptance_model_artifact_path

    if provider == "xgboost" and artifact_path:
        try:
            return XGBoostAcceptanceModel(artifact_path)
        except Exception as exc:
            logger.warning("xgboost acceptance model load failed (%s), using baseline", exc)

    if provider == "sklearn" and artifact_path:
        try:
            return SklearnAcceptanceModel(artifact_path)
        except Exception as exc:
            logger.warning("sklearn acceptance model load failed (%s), using baseline", exc)

    return BaselineAcceptanceProbabilityModel()

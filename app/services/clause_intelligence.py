import hashlib
import logging
import re
from typing import Protocol

import numpy as np

logger = logging.getLogger(__name__)

CLAUSE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "warranty": ("warranty", "warranties", "express warranty", "implied warranty"),
    "indemnity": ("indemn", "hold harmless", "defend"),
    "limitation_of_liability": ("limitation of liability", "liability cap", "aggregate liability"),
    "termination": ("terminate", "termination", "for convenience", "for cause"),
    "ip_ownership": ("intellectual property", "ownership", "ip rights"),
    "confidentiality": ("confidential", "non-disclosure", "nda"),
    "force_majeure": ("force majeure", "acts of god", "beyond reasonable control"),
    "insurance": ("insurance", "coverage", "policy limits"),
    "governing_law": ("governing law", "jurisdiction", "venue"),
}


class ClassificationResult:
    def __init__(self, clause_type: str, confidence: float) -> None:
        self.clause_type = clause_type
        self.confidence = confidence


class ClauseClassifier(Protocol):
    def classify(self, clause_text: str) -> ClassificationResult:
        ...


class EmbeddingProvider(Protocol):
    @property
    def embedding_dim(self) -> int:
        ...

    def embed(self, text: str) -> list[float]:
        ...


class KeywordClauseClassifier:
    def classify(self, clause_text: str) -> ClassificationResult:
        text = clause_text.lower()
        for clause_type, keywords in CLAUSE_KEYWORDS.items():
            if any(keyword in text for keyword in keywords):
                return ClassificationResult(clause_type=clause_type, confidence=0.86)
        return ClassificationResult(clause_type="other", confidence=0.55)


class SklearnClauseClassifier:
    def __init__(self, artifact_path: str) -> None:
        import joblib

        self.model = joblib.load(artifact_path)

    def classify(self, clause_text: str) -> ClassificationResult:
        if hasattr(self.model, "predict_proba"):
            probs = self.model.predict_proba([clause_text])[0]
            idx = int(np.argmax(probs))
            label = str(self.model.classes_[idx])
            confidence = float(probs[idx])
            return ClassificationResult(clause_type=label, confidence=confidence)

        label = str(self.model.predict([clause_text])[0])
        return ClassificationResult(clause_type=label, confidence=0.7)


class DeterministicEmbeddingProvider:
    def __init__(self, embedding_dim: int) -> None:
        self._embedding_dim = embedding_dim

    @property
    def embedding_dim(self) -> int:
        return self._embedding_dim

    def embed(self, text: str) -> list[float]:
        seed_hex = hashlib.md5(text.encode("utf-8"), usedforsecurity=False).hexdigest()[:8]
        seed = int(seed_hex, 16)
        rng = np.random.default_rng(seed)
        vector = rng.normal(size=self._embedding_dim)
        norm = np.linalg.norm(vector)
        if norm == 0:
            return vector.tolist()
        return (vector / norm).tolist()


class SentenceTransformerEmbeddingProvider:
    def __init__(self, model_name: str) -> None:
        from sentence_transformers import SentenceTransformer

        self.model = SentenceTransformer(model_name)
        self._embedding_dim = int(self.model.get_sentence_embedding_dimension())

    @property
    def embedding_dim(self) -> int:
        return self._embedding_dim

    def embed(self, text: str) -> list[float]:
        vector = self.model.encode(text, normalize_embeddings=True)
        return [float(x) for x in np.asarray(vector, dtype=np.float32).tolist()]


class ClauseIntelligenceService:
    def __init__(self, classifier: ClauseClassifier, embedder: EmbeddingProvider) -> None:
        self.classifier = classifier
        self.embedder = embedder
        self.embedding_dim = embedder.embedding_dim

    def segment(self, raw_text: str) -> list[str]:
        blocks = [x.strip() for x in re.split(r"\n\s*\n", raw_text) if x.strip()]
        if blocks:
            return blocks
        sentences = [x.strip() for x in re.split(r"(?<=[.!?])\s+", raw_text) if x.strip()]
        return sentences or [raw_text.strip()]

    def classify(self, clause_text: str) -> ClassificationResult:
        return self.classifier.classify(clause_text)

    def embed(self, clause_text: str) -> list[float]:
        return self.embedder.embed(clause_text)


def build_clause_intelligence_service(settings) -> ClauseIntelligenceService:
    classifier_provider = settings.clause_classifier_provider.lower()
    embedding_provider = settings.embedding_provider.lower()

    classifier: ClauseClassifier
    if classifier_provider == "sklearn" and settings.clause_classifier_artifact_path:
        try:
            classifier = SklearnClauseClassifier(settings.clause_classifier_artifact_path)
        except Exception as exc:
            logger.warning("clause classifier artifact load failed (%s), falling back to keyword", exc)
            classifier = KeywordClauseClassifier()
    else:
        classifier = KeywordClauseClassifier()

    embedder: EmbeddingProvider
    if embedding_provider == "sentence_transformers":
        try:
            embedder = SentenceTransformerEmbeddingProvider(settings.embedding_model_name)
        except Exception as exc:
            logger.warning("sentence-transformer load failed (%s), falling back to deterministic", exc)
            embedder = DeterministicEmbeddingProvider(settings.embedding_dim)
    else:
        embedder = DeterministicEmbeddingProvider(settings.embedding_dim)

    return ClauseIntelligenceService(classifier=classifier, embedder=embedder)

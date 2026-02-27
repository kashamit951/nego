import logging
import re
from typing import Any

from qdrant_client import QdrantClient, models as qmodels

from app.config import Settings

logger = logging.getLogger(__name__)


class VectorStore:
    def __init__(self, settings: Settings, embedding_dim: int | None = None) -> None:
        self.embedding_dim = embedding_dim or settings.embedding_dim
        self.client = QdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key)
        self._qdrant_available = True

    @staticmethod
    def tenant_collection(tenant_id: str) -> str:
        safe = re.sub(r"[^a-zA-Z0-9_]", "_", tenant_id)
        return f"{safe}_contracts"

    def ensure_collection(self, tenant_id: str) -> str:
        if not self._qdrant_available:
            return self.tenant_collection(tenant_id)
        collection_name = self.tenant_collection(tenant_id)
        try:
            self.client.get_collection(collection_name=collection_name)
        except Exception:
            try:
                self.client.create_collection(
                    collection_name=collection_name,
                    vectors_config=qmodels.VectorParams(
                        size=self.embedding_dim,
                        distance=qmodels.Distance.COSINE,
                    ),
                )
            except Exception as exc:
                self._qdrant_available = False
                logger.warning("qdrant unavailable, disabling vector ops for process lifetime: %s", exc)
        return collection_name

    def upsert_clause(
        self,
        tenant_id: str,
        point_id: str,
        vector: list[float],
        payload: dict[str, Any],
    ) -> None:
        if not self._qdrant_available:
            return
        try:
            collection_name = self.ensure_collection(tenant_id)
            if not self._qdrant_available:
                return
            self.client.upsert(
                collection_name=collection_name,
                points=[
                    qmodels.PointStruct(
                        id=point_id,
                        vector=vector,
                        payload=payload,
                    )
                ],
                wait=False,
            )
        except Exception as exc:
            self._qdrant_available = False
            logger.warning("qdrant upsert skipped: %s", exc)

    def search(
        self,
        tenant_id: str,
        query_vector: list[float],
        top_k: int,
        clause_type: str | None = None,
        client_id: str | None = None,
        source_type: str | None = None,
    ) -> list[dict[str, Any]]:
        if not self._qdrant_available:
            return []
        collection_name = self.tenant_collection(tenant_id)
        must_filters = []
        if clause_type:
            must_filters.append(
                qmodels.FieldCondition(
                    key="clause_type",
                    match=qmodels.MatchValue(value=clause_type),
                )
            )
        if client_id:
            must_filters.append(
                qmodels.FieldCondition(
                    key="client_id",
                    match=qmodels.MatchValue(value=client_id),
                )
            )
        if source_type:
            must_filters.append(
                qmodels.FieldCondition(
                    key="source_type",
                    match=qmodels.MatchValue(value=source_type),
                )
            )
        filters = qmodels.Filter(must=must_filters) if must_filters else None
        try:
            # qdrant-client newer versions expose query_points(), while older
            # versions expose search(). Support both to avoid runtime breakage.
            if hasattr(self.client, "query_points"):
                response = self.client.query_points(
                    collection_name=collection_name,
                    query=query_vector,
                    query_filter=filters,
                    limit=top_k,
                    with_payload=True,
                )
                results = getattr(response, "points", None) or response
            else:
                results = self.client.search(
                    collection_name=collection_name,
                    query_vector=query_vector,
                    query_filter=filters,
                    limit=top_k,
                    with_payload=True,
                )
        except Exception as exc:
            # Keep process alive; disable vector ops only if qdrant itself is unavailable.
            self._qdrant_available = False
            logger.warning("qdrant search skipped: %s", exc)
            return []

        hits: list[dict[str, Any]] = []
        for item in results:
            # qdrant client versions may return ScoredPoint objects or tuple-like rows.
            score = 0.0
            payload: dict[str, Any] = {}
            point_id_obj = None
            if hasattr(item, "id"):
                point_id_obj = getattr(item, "id", None)
                score = self._safe_float(getattr(item, "score", 0.0))
                raw_payload = getattr(item, "payload", None)
                payload = raw_payload if isinstance(raw_payload, dict) else {}
            elif isinstance(item, tuple):
                # Tuple shapes vary by qdrant client version; extract defensively.
                point_obj = next((part for part in item if hasattr(part, "id")), None)
                if point_obj is not None:
                    point_id_obj = getattr(point_obj, "id", None)
                    raw_payload = getattr(point_obj, "payload", None)
                    payload = raw_payload if isinstance(raw_payload, dict) else {}
                    raw_score = getattr(point_obj, "score", None)
                    score = self._safe_float(raw_score)
                if point_id_obj is None and len(item) > 0:
                    point_id_obj = item[0]
                if not payload:
                    tuple_payload = next((part for part in item if isinstance(part, dict)), None)
                    if isinstance(tuple_payload, dict):
                        payload = tuple_payload
                if score == 0.0:
                    numeric_part = next((part for part in item if isinstance(part, (int, float))), None)
                    if isinstance(numeric_part, (int, float)):
                        score = self._safe_float(numeric_part)
            else:
                continue
            point_id = str(point_id_obj)
            hits.append(
                {
                    "point_id": point_id,
                    "score": score,
                    "payload": payload,
                }
            )
        return hits

    @staticmethod
    def _safe_float(value: Any, default: float = 0.0) -> float:
        if isinstance(value, bool):
            return default
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            try:
                return float(value.strip())
            except Exception:
                return default
        return default

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.audit_routes import router as audit_router
from app.api.auth_routes import router as auth_router
from app.api.corpus_routes import router as corpus_router
from app.api.routes import router as contract_router
from app.config import get_settings
from app.db import models as _models  # noqa: F401
from app.db.base import Base
from app.db.session import engine

settings = get_settings()
settings.assert_llm_only()
app = FastAPI(title=settings.app_name)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:4200",
        "http://127.0.0.1:4200",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(contract_router)
app.include_router(auth_router)
app.include_router(audit_router)
app.include_router(corpus_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


if settings.enable_autocreate_schema:
    Base.metadata.create_all(bind=engine)

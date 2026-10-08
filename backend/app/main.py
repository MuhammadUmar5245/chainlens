from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.api import analytics, chains, datasets, jobs, uploads, wallets
from app.config import settings
from app.db.clickhouse import get_ch
from app.db.postgres import SessionLocal

app = FastAPI(title="Chainlens API", version="0.1.0",
              description="On-chain behaviour analytics: ingest, analyse and explore wallet behaviour on five EVM chains.")
app.add_middleware(CORSMiddleware, allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
                   allow_methods=["*"], allow_headers=["*"])

api = APIRouter(prefix="/api/v1")
for module in (chains, datasets, uploads, jobs, analytics, wallets):
    api.include_router(module.router)


@api.get("/health", tags=["health"])
def health():
    status = {"postgres": "ok", "clickhouse": "ok", "nownodes_key": bool(settings.nownodes_api_key),
              "history_days": settings.history_days}
    try:
        with SessionLocal() as s:
            s.execute(text("SELECT 1"))
    except Exception as e:
        status["postgres"] = f"error: {e}"
    try:
        get_ch().command("SELECT 1")
    except Exception as e:
        status["clickhouse"] = f"error: {e}"
    return status


app.include_router(api)

"""
Foo Management — Demo API
FastAPI + SQLAlchemy + OpenTelemetry → Grafana Cloud Tempo
"""

import os
import hashlib
import subprocess
import time
import logging
import urllib.parse as _urlparse

import requests as _requests

from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

# ─── OpenTelemetry setup (must run before app/engine creation) ────────────────
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource, SERVICE_NAME
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.instrumentation.requests import RequestsInstrumentor

OTEL_ENDPOINT = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "http://otel-collector:4317")

resource = Resource.create({SERVICE_NAME: "foo-api"})
provider = TracerProvider(resource=resource)
provider.add_span_processor(
    BatchSpanProcessor(OTLPSpanExporter(endpoint=OTEL_ENDPOINT, insecure=True))
)
trace.set_tracer_provider(provider)
tracer = trace.get_tracer("foo-api")

RequestsInstrumentor().instrument()

# Base URL for the batch service (strip path from the /run endpoint URL)
_batch_parsed = _urlparse.urlparse(os.environ.get("BATCH_SERVICE_URL", "http://foo-batch:8001/run"))
BATCH_BASE_URL = _urlparse.urlunparse(_batch_parsed._replace(path="", query="", fragment=""))

# ─── Database ─────────────────────────────────────────────────────────────────
MSSQL_HOST = os.environ.get("MSSQL_HOST", "sqlserver")
MSSQL_PORT = os.environ.get("MSSQL_PORT", "1433")
MSSQL_USER = os.environ.get("MSSQL_USER", "sa")
MSSQL_PASS = os.environ.get("MSSQL_SA_PASSWORD", "FooDemo!2024")
MSSQL_DB   = os.environ.get("MSSQL_DB", "foo")

conn_str = f"mssql+pymssql://{MSSQL_USER}:{MSSQL_PASS}@{MSSQL_HOST}:{MSSQL_PORT}/{MSSQL_DB}"

engine = create_engine(conn_str, pool_pre_ping=True, echo=False)
SessionLocal = sessionmaker(bind=engine)

# Instrument SQLAlchemy after engine creation
SQLAlchemyInstrumentor().instrument(engine=engine, enable_commenter=True)

# ─── FastAPI app ──────────────────────────────────────────────────────────────
app = FastAPI(title="Foo Management API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

FastAPIInstrumentor.instrument_app(app, tracer_provider=provider)

logger = logging.getLogger("foo-api")
logging.basicConfig(level=logging.INFO)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ─── Auth helpers ─────────────────────────────────────────────────────────────
security = HTTPBearer(auto_error=False)

def _sha256(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()

def _verify_token(creds: HTTPAuthorizationCredentials | None) -> dict:
    """Toy token check — real JWT validation not in scope for this demo."""
    if creds is None:
        raise HTTPException(status_code=401, detail="Missing token")
    # Token format:  sha256(username:demo123):<user_id>
    parts = creds.credentials.split(":")
    if len(parts) != 2:
        raise HTTPException(status_code=401, detail="Invalid token")
    return {"user_id": int(parts[1])}


# ─── Models ───────────────────────────────────────────────────────────────────
class LoginRequest(BaseModel):
    username: str
    password: str


# ─── Routes ───────────────────────────────────────────────────────────────────

@app.get("/api/health")
def health():
    return {"status": "ok", "service": "foo-api"}


@app.post("/api/login")
def login(req: LoginRequest, db: Session = Depends(get_db)):
    with tracer.start_as_current_span("foo.login") as span:
        span.set_attribute("foo.user.username", req.username)

        row = db.execute(
            text("SELECT id, password_hash FROM users WHERE username = :u"),
            {"u": req.username},
        ).fetchone()

        if row is None or row.password_hash != _sha256(req.password):
            span.set_attribute("foo.login.success", False)
            raise HTTPException(status_code=401, detail="Invalid credentials")

        span.set_attribute("foo.login.success", True)
        span.set_attribute("foo.user.id", row.id)

        token = f"{_sha256(req.username + ':' + req.password)}:{row.id}"
        return {"token": token, "user_id": row.id}


@app.get("/api/portfolio/{portfolio_id}")
def get_portfolio(
    portfolio_id: int,
    db: Session = Depends(get_db),
    creds: HTTPAuthorizationCredentials = Depends(security),
):
    ctx = _verify_token(creds)

    with tracer.start_as_current_span("foo.portfolio.fetch") as span:
        span.set_attribute("foo.portfolio.id", portfolio_id)
        span.set_attribute("foo.user.id", ctx["user_id"])

        portfolio = db.execute(
            text("SELECT id, name, aum, currency FROM portfolios WHERE id = :pid"),
            {"pid": portfolio_id},
        ).fetchone()

        if portfolio is None:
            raise HTTPException(status_code=404, detail="Portfolio not found")

        positions = db.execute(
            text(
                "SELECT ticker, quantity, cost_basis, market_value "
                "FROM positions WHERE portfolio_id = :pid "
                "ORDER BY market_value DESC"
            ),
            {"pid": portfolio_id},
        ).fetchall()

        span.set_attribute("foo.query.row_count", len(positions))
        span.set_attribute("foo.portfolio.name", portfolio.name)
        span.set_attribute("foo.portfolio.aum", float(portfolio.aum))

        return {
            "portfolio": {
                "id": portfolio.id,
                "name": portfolio.name,
                "aum": float(portfolio.aum),
                "currency": portfolio.currency.strip(),
            },
            "positions": [
                {
                    "ticker": p.ticker,
                    "quantity": float(p.quantity),
                    "cost_basis": float(p.cost_basis),
                    "market_value": float(p.market_value),
                }
                for p in positions
            ],
        }


@app.get("/api/trades")
def get_trades(
    portfolio_id: int,
    db: Session = Depends(get_db),
    creds: HTTPAuthorizationCredentials = Depends(security),
):
    _verify_token(creds)

    with tracer.start_as_current_span("foo.trades.fetch") as span:
        span.set_attribute("foo.portfolio.id", portfolio_id)

        rows = db.execute(
            text(
                "SELECT TOP 20 id, ticker, quantity, price, side, status, trade_date "
                "FROM trades WHERE portfolio_id = :pid "
                "ORDER BY trade_date DESC"
            ),
            {"pid": portfolio_id},
        ).fetchall()

        span.set_attribute("foo.query.row_count", len(rows))

        return {
            "trades": [
                {
                    "id": r.id,
                    "ticker": r.ticker,
                    "quantity": float(r.quantity),
                    "price": float(r.price),
                    "side": r.side.strip(),
                    "status": r.status,
                    "trade_date": r.trade_date.isoformat(),
                }
                for r in rows
            ]
        }


@app.post("/api/batch/trigger")
def trigger_batch(creds: HTTPAuthorizationCredentials = Depends(security)):
    _verify_token(creds)

    with tracer.start_as_current_span("foo.batch.trigger") as span:
        slow_step = os.environ.get("BATCH_SLOW_STEP", "")
        span.set_attribute("foo.batch.slow_step", slow_step or "none")

        # Fire batch runner as a background subprocess so the API returns quickly
        env = os.environ.copy()
        subprocess.Popen(
            ["python", "/app/batch_runner_stub.py"],
            env=env,
        )

        return {"status": "triggered", "message": "EOD batch started — check Grafana Tempo"}


@app.post("/api/batch/trigger-long")
def trigger_long_batch(creds: HTTPAuthorizationCredentials = Depends(security)):
    _verify_token(creds)

    with tracer.start_as_current_span("foo.batch.trigger_long") as span:
        try:
            resp = _requests.post(f"{BATCH_BASE_URL}/run-long", timeout=10)
            resp.raise_for_status()
            data = resp.json()
            span.set_attribute("foo.batch.run_id", data.get("run_id", ""))
            span.set_attribute("foo.batch.step_seconds", data.get("step_seconds", 0))
            return data
        except Exception as exc:
            span.record_exception(exc)
            raise HTTPException(status_code=502, detail=f"Batch service error: {exc}")


@app.post("/api/batch/trigger-links")
def trigger_links_batch(creds: HTTPAuthorizationCredentials = Depends(security)):
    _verify_token(creds)
    with tracer.start_as_current_span("foo.batch.trigger_links") as span:
        try:
            resp = _requests.post(f"{BATCH_BASE_URL}/run-links", timeout=10)
            resp.raise_for_status()
            data = resp.json()
            span.set_attribute("foo.batch.run_id",   data.get("run_id", ""))
            span.set_attribute("foo.batch.trace_id", data.get("trace_id", ""))
            return data
        except Exception as exc:
            span.record_exception(exc)
            raise HTTPException(status_code=502, detail=f"Batch service error: {exc}")


@app.get("/api/batch/status/{run_id}")
def get_long_batch_status(
    run_id: str,
    creds: HTTPAuthorizationCredentials = Depends(security),
):
    _verify_token(creds)

    try:
        resp = _requests.get(f"{BATCH_BASE_URL}/status/{run_id}", timeout=10)
        if resp.status_code == 404:
            raise HTTPException(status_code=404, detail="run_id not found")
        resp.raise_for_status()
        return resp.json()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Batch service error: {exc}")

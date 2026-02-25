"""
Foo Management — EOD Batch Runner
Simulates the 6-step end-of-day trade close with full OTel distributed tracing.

Service name: foo-batch-runner        (regular, runs every 60s)
Service name: foo-batch-runner-long   (on-demand, 15 min per step)

Environment:
  BATCH_SLOW_STEP            — integer 1-6, injects extra latency to simulate SLA breach
  LONG_BATCH_STEP_SECONDS    — seconds per step for the long batch (default 900 = 15 min)
  OTEL_EXPORTER_OTLP_ENDPOINT — gRPC endpoint for the OTel collector
"""

import os
import time
import uuid
import random
import logging
import threading
from threading import Lock

import uvicorn
from fastapi import FastAPI, HTTPException
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from opentelemetry import trace
from opentelemetry import context as otel_context
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource, SERVICE_NAME
from opentelemetry.trace import SpanKind, StatusCode, Link
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("foo-batch")

# ─── OTel — regular batch (service.name = foo-batch-runner) ─────────────────
OTEL_ENDPOINT = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "http://otel-collector:4317")

resource = Resource.create({SERVICE_NAME: "foo-batch-runner"})
provider = TracerProvider(resource=resource)
provider.add_span_processor(
    BatchSpanProcessor(OTLPSpanExporter(endpoint=OTEL_ENDPOINT, insecure=True))
)
trace.set_tracer_provider(provider)
tracer = trace.get_tracer("foo-batch-runner")

# ─── OTel — long batch (service.name = foo-batch-runner-long) ───────────────
# Uses its own TracerProvider — never set as the global provider.
LONG_BATCH_STEP_SECONDS = int(os.environ.get("LONG_BATCH_STEP_SECONDS", "900"))

long_resource = Resource.create({SERVICE_NAME: "foo-batch-runner-long"})
long_provider = TracerProvider(resource=long_resource)
long_provider.add_span_processor(
    BatchSpanProcessor(OTLPSpanExporter(endpoint=OTEL_ENDPOINT, insecure=True))
)
long_tracer = long_provider.get_tracer("foo-batch-runner-long")

# ─── OTel — links batch (service.name = foo-batch-runner-links) ─────────────
links_resource = Resource.create({SERVICE_NAME: "foo-batch-runner-links"})
links_provider = TracerProvider(resource=links_resource)
links_provider.add_span_processor(
    BatchSpanProcessor(OTLPSpanExporter(endpoint=OTEL_ENDPOINT, insecure=True))
)
links_tracer = links_provider.get_tracer("foo-batch-runner-links")

# ─── Database ─────────────────────────────────────────────────────────────────
MSSQL_HOST = os.environ.get("MSSQL_HOST", "sqlserver")
MSSQL_PORT = os.environ.get("MSSQL_PORT", "1433")
MSSQL_USER = os.environ.get("MSSQL_USER", "sa")
MSSQL_PASS = os.environ.get("MSSQL_SA_PASSWORD", "FooDemo!2024")
MSSQL_DB   = os.environ.get("MSSQL_DB", "foo")

conn_str = f"mssql+pymssql://{MSSQL_USER}:{MSSQL_PASS}@{MSSQL_HOST}:{MSSQL_PORT}/{MSSQL_DB}"

engine = create_engine(conn_str, pool_pre_ping=True, echo=False)
SessionLocal = sessionmaker(bind=engine)
SQLAlchemyInstrumentor().instrument(engine=engine, enable_commenter=True)

# ─── Step SLA thresholds (ms) ─────────────────────────────────────────────────
STEP_SLAS = {
    "load-trades":        500,
    "validate-positions": 800,
    "price-securities":  1200,
    "calculate-pnl":      900,
    "generate-reports":   600,
    "close-books":        700,
}

SLOW_STEP_NUM = int(os.environ.get("BATCH_SLOW_STEP", "0"))

STEPS = [
    "load-trades",
    "validate-positions",
    "price-securities",
    "calculate-pnl",
    "generate-reports",
    "close-books",
]

# ─── Long-batch run state ─────────────────────────────────────────────────────
# Keyed by run_id (uuid string). Entries persist for the container lifetime.
# Structure per entry:
#   status:          "running" | "complete" | "error"
#   current_step_idx: int (0-based; -1 = not yet started)
#   started_at:       float  (time.time() of batch start)
#   step_started_at:  float  (time.time() of current step start)
#   steps:            list of {name, status, started_at, duration_ms}
run_state: dict = {}
run_state_lock = Lock()


# ─── Individual step logic ────────────────────────────────────────────────────

def step_load_trades(db, span):
    rows = db.execute(
        text("SELECT id, ticker, quantity, price FROM trades WHERE status = 'pending'")
    ).fetchall()
    span.set_attribute("foo.batch.pending_trades", len(rows))
    return [dict(r._mapping) for r in rows]


def step_validate_positions(db, span):
    rows = db.execute(
        text(
            "SELECT p.ticker, p.quantity AS pos_qty, SUM(t.quantity) AS trade_qty "
            "FROM positions p "
            "JOIN trades t ON p.portfolio_id = t.portfolio_id AND p.ticker = t.ticker "
            "WHERE t.status = 'pending' "
            "GROUP BY p.ticker, p.quantity"
        )
    ).fetchall()
    span.set_attribute("foo.batch.validated_positions", len(rows))

    db.execute(
        text("UPDATE trades SET status = 'validated' WHERE status = 'pending'")
    )
    db.commit()


def step_price_securities(db, span):
    rows = db.execute(text("SELECT id, market_value FROM positions")).fetchall()
    for r in rows:
        new_val = float(r.market_value) * (1 + random.uniform(-0.005, 0.005))
        db.execute(
            text("UPDATE positions SET market_value = :mv, updated_at = GETUTCDATE() WHERE id = :id"),
            {"mv": round(new_val, 2), "id": r.id},
        )
    db.commit()
    span.set_attribute("foo.batch.positions_priced", len(rows))


def step_calculate_pnl(db, span):
    rows = db.execute(
        text(
            "SELECT portfolio_id, "
            "  SUM((market_value - cost_basis * quantity)) AS pnl "
            "FROM positions "
            "GROUP BY portfolio_id"
        )
    ).fetchall()
    span.set_attribute("foo.batch.portfolios_calculated", len(rows))
    return [dict(r._mapping) for r in rows]


def step_generate_reports(db, span, pnl_data):
    trade_counts = db.execute(
        text(
            "SELECT portfolio_id, COUNT(*) AS cnt "
            "FROM trades WHERE status = 'validated' "
            "GROUP BY portfolio_id"
        )
    ).fetchall()
    tc_map = {r.portfolio_id: r.cnt for r in trade_counts}

    for pnl in pnl_data:
        pid = pnl["portfolio_id"]
        db.execute(
            text(
                "INSERT INTO batch_reports (portfolio_id, total_pnl, trade_count, status) "
                "VALUES (:pid, :pnl, :tc, 'complete')"
            ),
            {
                "pid": pid,
                "pnl": round(float(pnl["pnl"]), 2),
                "tc": tc_map.get(pid, 0),
            },
        )
    db.commit()
    span.set_attribute("foo.batch.reports_generated", len(pnl_data))


def step_close_books(db, span):
    result = db.execute(
        text("UPDATE trades SET status = 'settled' WHERE status = 'validated'")
    )
    db.commit()
    span.set_attribute("foo.batch.trades_settled", result.rowcount)


# ─── Regular batch orchestrator (short delays, SLA breach simulation) ─────────

def run_eod_batch():
    logger.info("Starting EOD batch close...")
    db = SessionLocal()
    pnl_data = []

    with tracer.start_as_current_span("eod-batch-close", kind=SpanKind.INTERNAL) as parent:
        parent.set_attribute("foo.batch.run_date", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
        parent.set_attribute("foo.batch.step_count", len(STEPS))
        parent.set_attribute("foo.batch.slow_step", SLOW_STEP_NUM)

        step_funcs = {
            "load-trades":        lambda db, sp: step_load_trades(db, sp),
            "validate-positions": lambda db, sp: step_validate_positions(db, sp),
            "price-securities":   lambda db, sp: step_price_securities(db, sp),
            "calculate-pnl":      lambda db, sp: (pnl_data.extend(step_calculate_pnl(db, sp) or []) or None),
            "generate-reports":   lambda db, sp: step_generate_reports(db, sp, pnl_data),
            "close-books":        lambda db, sp: step_close_books(db, sp),
        }

        for idx, step_name in enumerate(STEPS, start=1):
            sla_ms = STEP_SLAS[step_name]

            with tracer.start_as_current_span(step_name) as span:
                span.set_attribute("foo.batch.step",     step_name)
                span.set_attribute("foo.batch.step_num", idx)
                span.set_attribute("foo.batch.sla_ms",   sla_ms)

                t0 = time.time()
                try:
                    base_delay = random.uniform(0.05, 0.15)
                    if idx == SLOW_STEP_NUM:
                        slow_extra = random.uniform(1.5, 2.5)
                        logger.warning(f"[step {idx}] Injecting SLA-breach delay: {slow_extra:.2f}s")
                        time.sleep(slow_extra)
                    else:
                        time.sleep(base_delay)

                    step_funcs[step_name](db, span)

                    duration_ms = (time.time() - t0) * 1000
                    span.set_attribute("foo.batch.duration_ms", round(duration_ms, 1))
                    span.set_attribute("foo.batch.sla_breached", duration_ms > sla_ms)
                    span.set_attribute("foo.batch.status", "success")

                    if duration_ms > sla_ms:
                        logger.warning(f"[step {idx}:{step_name}] SLA BREACH — {duration_ms:.0f}ms > {sla_ms}ms")
                        span.set_status(StatusCode.ERROR, f"SLA breached: {duration_ms:.0f}ms > {sla_ms}ms")
                    else:
                        logger.info(f"[step {idx}:{step_name}] OK — {duration_ms:.0f}ms")

                except Exception as exc:
                    duration_ms = (time.time() - t0) * 1000
                    span.set_attribute("foo.batch.duration_ms", round(duration_ms, 1))
                    span.set_attribute("foo.batch.status", "error")
                    span.record_exception(exc)
                    span.set_status(StatusCode.ERROR, str(exc))
                    logger.error(f"[step {idx}:{step_name}] FAILED: {exc}")
                    db.rollback()
                    break

    db.close()
    logger.info("EOD batch close complete.")


# ─── Long-batch orchestrator (15 min per step, foo-batch-runner-long) ────────

def run_eod_batch_long(run_id: str):
    logger.info(f"[long:{run_id}] Starting long EOD batch — {LONG_BATCH_STEP_SECONDS}s per step")
    db = SessionLocal()
    pnl_data = []

    # Initialise per-step state now that we're in the thread
    with run_state_lock:
        run_state[run_id]["steps"] = [
            {"name": s, "status": "pending", "started_at": None, "duration_ms": None}
            for s in STEPS
        ]

    with long_tracer.start_as_current_span("eod-batch-close-long", kind=SpanKind.INTERNAL) as parent:
        parent.set_attribute("foo.batch.run_id",       run_id)
        parent.set_attribute("foo.batch.run_date",     time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
        parent.set_attribute("foo.batch.step_count",   len(STEPS))
        parent.set_attribute("foo.batch.step_seconds", LONG_BATCH_STEP_SECONDS)

        step_funcs = {
            "load-trades":        lambda db, sp: step_load_trades(db, sp),
            "validate-positions": lambda db, sp: step_validate_positions(db, sp),
            "price-securities":   lambda db, sp: step_price_securities(db, sp),
            "calculate-pnl":      lambda db, sp: (pnl_data.extend(step_calculate_pnl(db, sp) or []) or None),
            "generate-reports":   lambda db, sp: step_generate_reports(db, sp, pnl_data),
            "close-books":        lambda db, sp: step_close_books(db, sp),
        }

        for idx, step_name in enumerate(STEPS):
            step_start = time.time()
            with run_state_lock:
                run_state[run_id]["current_step_idx"] = idx
                run_state[run_id]["step_started_at"]  = step_start
                run_state[run_id]["steps"][idx]["status"]     = "running"
                run_state[run_id]["steps"][idx]["started_at"] = step_start

            with long_tracer.start_as_current_span(step_name) as span:
                span.set_attribute("foo.batch.step",         step_name)
                span.set_attribute("foo.batch.step_num",     idx + 1)
                span.set_attribute("foo.batch.run_id",       run_id)
                span.set_attribute("foo.batch.step_seconds", LONG_BATCH_STEP_SECONDS)

                t0 = time.time()
                try:
                    time.sleep(LONG_BATCH_STEP_SECONDS)
                    step_funcs[step_name](db, span)

                    duration_ms = (time.time() - t0) * 1000
                    span.set_attribute("foo.batch.duration_ms", round(duration_ms, 1))
                    span.set_attribute("foo.batch.status", "success")

                    with run_state_lock:
                        run_state[run_id]["steps"][idx]["status"]      = "complete"
                        run_state[run_id]["steps"][idx]["duration_ms"] = round(duration_ms, 1)

                    logger.info(f"[long:{run_id}] step {idx+1}/{len(STEPS)} {step_name} complete")

                except Exception as exc:
                    duration_ms = (time.time() - t0) * 1000
                    span.record_exception(exc)
                    span.set_status(StatusCode.ERROR, str(exc))
                    span.set_attribute("foo.batch.duration_ms", round(duration_ms, 1))
                    span.set_attribute("foo.batch.status", "error")

                    with run_state_lock:
                        run_state[run_id]["steps"][idx]["status"]      = "error"
                        run_state[run_id]["steps"][idx]["duration_ms"] = round(duration_ms, 1)
                        run_state[run_id]["status"] = "error"

                    logger.error(f"[long:{run_id}] step {idx+1} {step_name} FAILED: {exc}")
                    db.rollback()
                    db.close()
                    return

    db.close()
    with run_state_lock:
        run_state[run_id]["status"]           = "complete"
        run_state[run_id]["current_step_idx"] = len(STEPS)
    logger.info(f"[long:{run_id}] Long EOD batch complete.")


# ─── Links-batch orchestrator (each step = independent root span with link) ───

def run_eod_batch_links(run_id: str, coordinator_span):
    """Each step is an independent root span linked to coordinator_span."""
    logger.info(f"[links:{run_id}] Starting links EOD batch")
    db = SessionLocal()
    pnl_data = []
    coordinator_ctx = coordinator_span.get_span_context()

    step_funcs = {
        "load-trades":        lambda db, sp: step_load_trades(db, sp),
        "validate-positions": lambda db, sp: step_validate_positions(db, sp),
        "price-securities":   lambda db, sp: step_price_securities(db, sp),
        "calculate-pnl":      lambda db, sp: (pnl_data.extend(step_calculate_pnl(db, sp) or []) or None),
        "generate-reports":   lambda db, sp: step_generate_reports(db, sp, pnl_data),
        "close-books":        lambda db, sp: step_close_books(db, sp),
    }

    try:
        for idx, step_name in enumerate(STEPS, start=1):
            empty_ctx = otel_context.Context()   # no parent → root span
            step_span = links_tracer.start_span(
                step_name,
                context=empty_ctx,
                kind=SpanKind.INTERNAL,
                links=[Link(coordinator_ctx)],
                attributes={
                    "foo.batch.step":     step_name,
                    "foo.batch.step_num": idx,
                    "foo.batch.run_id":   run_id,
                },
            )
            token = otel_context.attach(trace.set_span_in_context(step_span))
            t0 = time.time()
            try:
                time.sleep(1)
                step_funcs[step_name](db, step_span)
                duration_ms = (time.time() - t0) * 1000
                step_span.set_attribute("foo.batch.duration_ms", round(duration_ms, 1))
                step_span.set_attribute("foo.batch.status", "success")
                logger.info(f"[links:{run_id}] step {idx}/{len(STEPS)} {step_name} complete")
            except Exception as exc:
                step_span.record_exception(exc)
                step_span.set_status(StatusCode.ERROR, str(exc))
                step_span.set_attribute("foo.batch.status", "error")
                logger.error(f"[links:{run_id}] step {idx} {step_name} FAILED: {exc}")
                db.rollback()
            finally:
                otel_context.detach(token)
                step_span.end()
    finally:
        db.close()
        coordinator_span.set_attribute("foo.batch.run_id",     run_id)
        coordinator_span.set_attribute("foo.batch.step_count", len(STEPS))
        coordinator_span.end()
        logger.info(f"[links:{run_id}] Links EOD batch complete.")


# ─── HTTP app ─────────────────────────────────────────────────────────────────
http_app = FastAPI()


@http_app.get("/health")
def health():
    return {"status": "ok", "service": "foo-batch-runner"}


@http_app.post("/run")
def trigger():
    t = threading.Thread(target=run_eod_batch, daemon=True)
    t.start()
    return {"status": "started"}


@http_app.post("/run-long")
def trigger_long():
    run_id = str(uuid.uuid4())
    now = time.time()
    with run_state_lock:
        run_state[run_id] = {
            "status":           "running",
            "current_step_idx": -1,
            "started_at":       now,
            "step_started_at":  now,
            "steps":            [],   # populated inside run_eod_batch_long
        }
    t = threading.Thread(target=run_eod_batch_long, args=(run_id,), daemon=True)
    t.start()
    return {"run_id": run_id, "step_seconds": LONG_BATCH_STEP_SECONDS}


@http_app.post("/run-links")
def trigger_links():
    run_id = str(uuid.uuid4())
    coordinator_span = links_tracer.start_span(
        "batch-coordinator",
        kind=SpanKind.INTERNAL,
        attributes={"foo.batch.mode": "span-links", "foo.batch.run_id": run_id},
    )
    coordinator_trace_id = format(coordinator_span.get_span_context().trace_id, "032x")
    t = threading.Thread(target=run_eod_batch_links, args=(run_id, coordinator_span), daemon=True)
    t.start()
    return {"run_id": run_id, "trace_id": coordinator_trace_id}


@http_app.get("/status/{run_id}")
def get_status(run_id: str):
    with run_state_lock:
        state = run_state.get(run_id)

    if state is None:
        raise HTTPException(status_code=404, detail="run_id not found")

    now = time.time()
    total_elapsed_ms = round((now - state["started_at"]) * 1000, 1)

    # Live elapsed for the currently-running step
    step_elapsed_ms = 0.0
    current_idx = state["current_step_idx"]
    if state["status"] == "running" and 0 <= current_idx < len(STEPS):
        step_elapsed_ms = round((now - state["step_started_at"]) * 1000, 1)

    steps_completed = sum(1 for s in state["steps"] if s["status"] == "complete")

    return {
        "run_id":           run_id,
        "status":           state["status"],
        "steps_completed":  steps_completed,
        "total_steps":      len(STEPS),
        "total_elapsed_ms": total_elapsed_ms,
        "step_elapsed_ms":  step_elapsed_ms,
        "step_seconds":     LONG_BATCH_STEP_SECONDS,
        "current_step_idx": current_idx,
        "steps":            state["steps"],
    }


# ─── Scheduled loop (runs every 60s when container starts) ────────────────────
def schedule_loop():
    time.sleep(30)
    while True:
        run_eod_batch()
        time.sleep(60)


if __name__ == "__main__":
    bg = threading.Thread(target=schedule_loop, daemon=True)
    bg.start()
    uvicorn.run(http_app, host="0.0.0.0", port=8001)

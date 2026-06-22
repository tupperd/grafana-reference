"""FastAPI app: light auth, wardrobe CRUD, and three instrumented AI endpoints."""
import logging
import os
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from . import auth, config, db, llm, telemetry
from .models import (
    EvaluateRequest,
    ItemIn,
    LoginIn,
    OutfitChatRequest,
    OutfitRequest,
    ShoppingChatRequest,
    ShoppingRequest,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("wardrobe")

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    telemetry.init_telemetry()
    log.info("Wardrobe AI ready. Telemetry: %s", telemetry.status())
    yield
    telemetry.shutdown()


app = FastAPI(title="Wardrobe AI", lifespan=lifespan)
app.add_middleware(SessionMiddleware, secret_key=config.SESSION_SECRET)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def _ai(fn, *args, **kwargs):
    """Run an LLM call, translating LLM/connection failures into a clean 503."""
    try:
        return fn(*args, **kwargs)
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        log.warning("AI call failed: %s", e)
        raise HTTPException(
            status_code=503,
            detail=f"LLM call failed ({e}). Is Ollama running and the model pulled?",
        )


@app.get("/")
def index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


@app.get("/health")
def health():
    return {"status": "ok", "telemetry": telemetry.status(), "model": config.OLLAMA_MODEL}


@app.post("/api/login")
def login(body: LoginIn, request: Request):
    if not auth.check_credentials(body.username, body.password):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    request.session["user"] = body.username
    return {"user": body.username}


@app.post("/api/logout")
def logout(request: Request):
    request.session.clear()
    return {"ok": True}


@app.get("/api/me")
def me(request: Request, user=Depends(auth.require_user)):
    return {"user": user, "telemetry": telemetry.status(), "model": config.OLLAMA_MODEL}


@app.get("/api/items")
def get_items(user=Depends(auth.require_user)):
    return db.list_items()


@app.post("/api/items")
def create_item(item: ItemIn, user=Depends(auth.require_user)):
    return db.add_item(item.model_dump())


@app.delete("/api/items/{item_id}")
def remove_item(item_id: int, user=Depends(auth.require_user)):
    db.delete_item(item_id)
    return {"ok": True}


@app.post("/api/outfit")
def api_outfit(body: OutfitRequest, user=Depends(auth.require_user)):
    items = db.list_items()
    if body.item_ids:
        wanted = set(body.item_ids)
        items = [i for i in items if i["id"] in wanted]
    if not items:
        raise HTTPException(status_code=400, detail="No items in catalog to build from")
    return _ai(llm.build_outfit, items, body.occasion)


@app.post("/api/shopping")
def api_shopping(body: ShoppingRequest, user=Depends(auth.require_user)):
    return _ai(llm.shopping_list, db.list_items(), body.goal)


def _as_history(history_models, new_message: str) -> list[dict]:
    """Prior turns from the client + the new user message appended."""
    hist = [{"role": m.role, "content": m.content} for m in history_models]
    hist.append({"role": "user", "content": new_message})
    return hist


@app.post("/api/outfit/chat")
def api_outfit_chat(body: OutfitChatRequest, user=Depends(auth.require_user)):
    items = db.list_items()
    if body.item_ids:
        wanted = set(body.item_ids)
        items = [i for i in items if i["id"] in wanted]
    if not items:
        raise HTTPException(status_code=400, detail="No items in catalog to build from")
    history = _as_history(body.history, body.occasion)
    return _ai(llm.outfit_turn, items, body.conversation_id or None, history, run_research=body.run_research)


@app.post("/api/shopping/chat")
def api_shopping_chat(body: ShoppingChatRequest, user=Depends(auth.require_user)):
    history = _as_history(body.history, body.goal)
    return _ai(llm.shopping_turn, db.list_items(), body.conversation_id or None, history, run_research=body.run_research)


@app.post("/api/evaluate")
def api_evaluate(body: EvaluateRequest, user=Depends(auth.require_user)):
    if body.kind not in ("outfit", "shopping"):
        raise HTTPException(status_code=400, detail="kind must be 'outfit' or 'shopping'")
    return _ai(
        llm.judge,
        body.kind,
        body.context,
        body.output,
        conversation_id=body.conversation_id or None,
        parent_id=body.parent_generation_id or None,
    )

import asyncio
import hashlib
import hmac
import json
import logging
import os
import uuid
from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from jinja2 import Environment, FileSystemLoader
from fastapi.templating import Jinja2Templates

from card_builder import build_adaptive_card
from models import MeterWebhookPayload
from teams_sender import send_to_teams

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

METER_WEBHOOK_SECRET: str = os.getenv("METER_WEBHOOK_SECRET", "")


@dataclass
class TeamsDestination:
    id: str
    name: str
    url: str


def _load_destinations() -> list[TeamsDestination]:
    """Read TEAMS_DESTINATIONS JSON; fall back to legacy TEAMS_WEBHOOK_URL for back-compat."""
    raw = os.getenv("TEAMS_DESTINATIONS", "").strip()
    if raw:
        try:
            items = json.loads(raw)
            out: list[TeamsDestination] = []
            for it in items:
                url = (it.get("url") or "").strip()
                if not url:
                    continue
                out.append(TeamsDestination(
                    id=it.get("id") or str(uuid.uuid4()),
                    name=(it.get("name") or "Unnamed").strip() or "Unnamed",
                    url=url,
                ))
            return out
        except Exception as exc:
            logger.warning("Failed to parse TEAMS_DESTINATIONS: %s", exc)

    legacy = os.getenv("TEAMS_WEBHOOK_URL", "").strip()
    if legacy:
        return [TeamsDestination(id=str(uuid.uuid4()), name="Default", url=legacy)]
    return []


runtime_config: dict = {
    "destinations": _load_destinations(),
}


@dataclass
class EventLogEntry:
    id: str
    received_at: str
    alert_name: str
    network_name: str
    source: str          # "meter" | "test"
    original_payload: dict
    teams_payload: dict
    delivered: bool      # True when every configured destination accepted the card
    delivery_results: list = field(default_factory=list)  # [{id, name, delivered}]


event_log: deque[EventLogEntry] = deque(maxlen=50)

app = FastAPI(title="Meter → Teams Webhook Receiver")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# cache_size=0 avoids a Python 3.14 / Jinja2 LRU-cache tuple-key bug
_jinja_env = Environment(loader=FileSystemLoader("templates"), cache_size=0)
templates = Jinja2Templates(env=_jinja_env)


# ── UI ────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def ui(request: Request):
    return templates.TemplateResponse(request, "index.html", {
        "destination_count": len(runtime_config["destinations"]),
    })


@app.get("/health")
async def health():
    return {"status": "ok", "destination_count": len(runtime_config["destinations"])}


# ── API ───────────────────────────────────────────────────────────────

@app.get("/api/events")
async def api_events():
    return [asdict(e) for e in event_log]


@app.post("/api/preview")
async def api_preview(request: Request):
    """Build and return both payloads without sending to Teams."""
    raw = await request.json()
    try:
        payload = MeterWebhookPayload.model_validate(raw)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    card = build_adaptive_card(payload)
    return {"original_payload": raw, "teams_payload": card}


async def _broadcast(card: dict) -> tuple[bool, list[dict]]:
    """Fan-out the card to every destination in parallel.

    Returns (all_delivered, per-destination results). When there are zero
    destinations, all_delivered is False so the UI can flag the unconfigured state.
    """
    destinations = runtime_config["destinations"]
    if not destinations:
        return False, []

    oks = await asyncio.gather(*[send_to_teams(d.url, card) for d in destinations])
    results = [
        {"id": d.id, "name": d.name, "delivered": ok}
        for d, ok in zip(destinations, oks)
    ]
    return all(oks), results


@app.post("/api/send-test")
async def api_send_test(request: Request):
    """Build the card, broadcast to every destination, log the event, return everything."""
    raw = await request.json()
    try:
        payload = MeterWebhookPayload.model_validate(raw)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    card = build_adaptive_card(payload)
    all_delivered, results = await _broadcast(card)

    _log_event(payload, raw, card, all_delivered, source="test", delivery_results=results)
    delivered_n = sum(1 for r in results if r["delivered"])
    logger.info("Test event: alert=%s network=%s delivered=%d/%d",
                payload.metadata.alert_name, payload.metadata.network_name,
                delivered_n, len(results))

    return {
        "original_payload": raw,
        "teams_payload": card,
        "delivered": all_delivered,
        "delivery_results": results,
        "destination_count": len(runtime_config["destinations"]),
    }


# ── Meter webhook receiver ─────────────────────────────────────────────

@app.get("/webhook")
async def webhook_probe():
    """Responds to GET verification pings from webhook senders."""
    return JSONResponse(status_code=200, content={"status": "ok"})


@app.post("/webhook")
async def receive_webhook(request: Request) -> JSONResponse:
    body = await request.body()

    if METER_WEBHOOK_SECRET:
        signature = request.headers.get("x-meter-signature", "")
        expected = hmac.new(
            METER_WEBHOOK_SECRET.encode(),
            body,
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(expected, signature):
            raise HTTPException(status_code=401, detail="Invalid signature")

    try:
        raw = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    try:
        payload = MeterWebhookPayload.model_validate(raw)
    except Exception as exc:
        logger.warning("Payload validation failed: %s", exc)
        raise HTTPException(status_code=422, detail=str(exc))

    logger.info("Alert received: alert=%s network=%s", payload.metadata.alert_name, payload.metadata.network_name)

    card = build_adaptive_card(payload)

    if runtime_config["destinations"]:
        all_delivered, results = await _broadcast(card)
        delivered_n = sum(1 for r in results if r["delivered"])
        logger.info("Forwarded to %d/%d Teams destinations", delivered_n, len(results))
    else:
        all_delivered, results = False, []
        logger.warning("No Teams destinations configured — alert logged but not forwarded")

    _log_event(payload, raw, card, all_delivered, source="meter", delivery_results=results)

    return JSONResponse(status_code=200, content={
        "status": "ok",
        "delivered": all_delivered,
        "delivery_results": results,
    })


# ── Config API ────────────────────────────────────────────────────────

@app.get("/api/config")
async def get_config():
    return {
        "destinations": [_dest_summary(d) for d in runtime_config["destinations"]],
    }


@app.post("/api/config")
async def add_destination(request: Request):
    """Add a new Teams destination. Body: { name, url }."""
    body = await request.json()
    name = (body.get("name") or "").strip() or "Unnamed"
    url = (body.get("url") or "").strip()
    if not url:
        raise HTTPException(status_code=400, detail="URL is required")

    dest = TeamsDestination(id=str(uuid.uuid4()), name=name, url=url)
    runtime_config["destinations"].append(dest)
    _persist_destinations()
    logger.info("Added Teams destination: %s", name)
    return {
        "destinations": [_dest_summary(d) for d in runtime_config["destinations"]],
    }


@app.delete("/api/config/{dest_id}")
async def delete_destination(dest_id: str):
    before = len(runtime_config["destinations"])
    runtime_config["destinations"] = [
        d for d in runtime_config["destinations"] if d.id != dest_id
    ]
    if len(runtime_config["destinations"]) == before:
        raise HTTPException(status_code=404, detail="Destination not found")
    _persist_destinations()
    logger.info("Removed Teams destination: %s", dest_id)
    return {
        "destinations": [_dest_summary(d) for d in runtime_config["destinations"]],
    }


# ── Helpers ───────────────────────────────────────────────────────────

def _dest_summary(d: TeamsDestination) -> dict:
    return {"id": d.id, "name": d.name, "masked_url": _mask_url(d.url)}


def _mask_url(url: str) -> str:
    if len(url) <= 40:
        return url
    return url[:30] + "…" + url[-10:]


def _persist_destinations() -> None:
    """Serialize destinations to .env as JSON; clear the legacy single-URL var."""
    if runtime_config["destinations"]:
        value = json.dumps([asdict(d) for d in runtime_config["destinations"]])
    else:
        value = ""
    _persist_env("TEAMS_DESTINATIONS", value)
    _persist_env("TEAMS_WEBHOOK_URL", "")


def _persist_env(key: str, value: str) -> None:
    """Update or add a key in .env without touching other lines."""
    env_path = Path(".env")
    lines = env_path.read_text().splitlines() if env_path.exists() else []
    found = False
    new_lines = []
    for line in lines:
        if line.startswith(f"{key}=") or line.startswith(f"{key} ="):
            if value:
                new_lines.append(f"{key}={value}")
            found = True
        else:
            new_lines.append(line)
    if not found and value:
        new_lines.append(f"{key}={value}")
    env_path.write_text("\n".join(new_lines) + "\n")


def _log_event(
    payload: MeterWebhookPayload,
    raw: dict,
    card: dict,
    delivered: bool,
    source: str,
    delivery_results: list | None = None,
) -> None:
    event_log.appendleft(
        EventLogEntry(
            id=str(uuid.uuid4()),
            received_at=datetime.now(timezone.utc).isoformat(),
            alert_name=payload.metadata.alert_name,
            network_name=payload.metadata.network_name,
            source=source,
            original_payload=raw,
            teams_payload=card,
            delivered=delivered,
            delivery_results=delivery_results or [],
        )
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "8000")),
        reload=False,
    )

# meterWebhookReceiver

A lightweight FastAPI app that receives [Meter Dashboard alert webhooks](https://docs.meter.com/reference/webhooks/alert-events) and fans them out to one or more Microsoft Teams channels as richly formatted [Adaptive Cards](https://learn.microsoft.com/en-us/adaptive-cards/).

Ships with a web UI for configuring Teams destinations, sending test alerts, previewing rendered cards, and inspecting recent webhook deliveries.

## Features

- **Receives Meter alerts** at `POST /webhook` — handles all 25 documented alert types across Device, WAN, Access Point, Network, Switch, and Audit categories
- **Fan-out delivery** to multiple Teams destinations in parallel (`asyncio.gather`)
- **Adaptive Card translation** — severity-colored header, category subtitle, fact table with humanized field labels, and an "Open Meter Dashboard" action
- **Web UI** for:
  - Configuring Teams destinations (name + webhook URL) with add/remove
  - Triggering test events for any alert type and previewing the rendered card
  - Viewing the last 50 deliveries with per-destination status
- **Optional HMAC-SHA256 signature verification** via `METER_WEBHOOK_SECRET`
- **Teams 429 handling** with exponential backoff retry
- **No database** — in-memory event log, destinations persisted to `.env`

## Architecture

```
Meter Dashboard                                  ┌─── Teams channel A
     │                                           │
     └──► POST /webhook ──► FastAPI ──► fan-out ─┼─── Teams channel B
                              │                  │
                              │                  └─── Teams channel C
                              ▼
                          Adaptive Card
                          (card_builder.py)
```

| File | Purpose |
|---|---|
| `main.py` | FastAPI routes, webhook receiver, config API, event log |
| `models.py` | Pydantic models for incoming Meter payloads |
| `card_builder.py` | Meter payload → Teams Adaptive Card translation |
| `teams_sender.py` | HTTP delivery to Teams with retry/backoff |
| `templates/index.html` | Alpine.js single-page UI |

## Quick start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
uvicorn main:app --host 0.0.0.0 --port 8000
```

Open http://localhost:8000, click **Configure**, and add at least one Teams webhook URL.

## Configuration

All config lives in `.env` (copy from `.env.example`):

| Variable | Required | Description |
|---|---|---|
| `TEAMS_DESTINATIONS` | no | JSON array of `{id, name, url}`. Managed by the UI — no need to edit by hand. |
| `TEAMS_WEBHOOK_URL` | no | Legacy single-URL fallback. Read only if `TEAMS_DESTINATIONS` is empty, then auto-migrated on first UI save. |
| `METER_WEBHOOK_SECRET` | no | Optional HMAC-SHA256 signing secret. When set, incoming webhooks must include a matching `X-Meter-Signature` header. |
| `HOST` | no | Default `0.0.0.0` |
| `PORT` | no | Default `8000` |

## Exposing the receiver to Meter

Meter needs a publicly reachable HTTPS URL. The simplest option is a [Cloudflare Tunnel](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/):

```bash
cloudflared tunnel --url http://localhost:8000
```

Then set the webhook URL in the Meter Dashboard to `https://<your-tunnel>.trycloudflare.com/webhook`.

## Getting a Teams webhook URL

Either of these works as a destination URL:

- **Incoming Webhook** (legacy connector) — in a Teams channel: *Manage channel → Edit → Connectors → Incoming Webhook → Configure*
- **Power Automate HTTP trigger** — build a flow with "When an HTTP request is received" as the trigger and "Post adaptive card in a chat or channel" as the action (recommended; Microsoft is retiring the legacy connectors)

## API

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/` | Web UI |
| `GET` | `/health` | Health check, returns destination count |
| `POST` | `/webhook` | Receive Meter alert, forward to all destinations |
| `GET` | `/webhook` | Verification ping (returns 200) |
| `GET` | `/api/events` | List recent received events (max 50) |
| `POST` | `/api/preview` | Build card for a given payload without sending |
| `POST` | `/api/send-test` | Build + broadcast to all destinations |
| `GET` | `/api/config` | List configured destinations |
| `POST` | `/api/config` | Add a destination: `{name, url}` |
| `DELETE` | `/api/config/{id}` | Remove a destination by id |

## Tech stack

- **FastAPI** + **uvicorn** (async HTTP)
- **Pydantic v2** for payload validation
- **httpx** for async outbound delivery
- **Jinja2** templates
- **Alpine.js 3** + **Tailwind CSS** (Play CDN) for the UI
- **AdaptiveCards.js 2.11** for in-browser card rendering

## License

[MIT](LICENSE)

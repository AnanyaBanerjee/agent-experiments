"""
=============================================================================
📡 TECH FINDER AGENT — WhatsApp → Tavily Search → Top 5 Links
=============================================================================

Send any topic via WhatsApp and get the top 5 latest articles back instantly.

Example messages:
  "agent protocol"
  "latest AI chip news"
  "OpenAI vs Anthropic 2026"

Flow:
  1. Twilio receives your WhatsApp message and POSTs to /webhook
  2. Webhook returns empty TwiML immediately (beats Twilio's 15s timeout)
  3. Background task searches Tavily for the latest news on your topic
  4. Top 5 results (title + URL + date) are sent back via Twilio REST API

Setup:
  1. pip install -e ".[tech-finder]"

  2. Add to .env:
       TAVILY_API_KEY=your-tavily-api-key-here      ← https://tavily.com (free)
       TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
       TWILIO_AUTH_TOKEN=your-twilio-auth-token-here
       TWILIO_WHATSAPP_FROM=whatsapp:+14155238886

  3. Run:
       uvicorn tech_finder_agent.agent_tech_finder.agent_tech_finder:app --reload --port 8001

  4. Expose publicly (separate terminal):
       ngrok http 8001

  5. In Twilio sandbox console set "When a message comes in" to:
       https://<ngrok-id>.ngrok-free.app/webhook   (HTTP POST)

  6. Text the sandbox number any topic — links come back in seconds.
=============================================================================
"""

import asyncio
import json
import os
from datetime import datetime
from pathlib import Path

import httpx
from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request, Response
from twilio.request_validator import RequestValidator
from twilio.rest import Client

load_dotenv()

TAVILY_API_KEY = os.environ.get("TAVILY_API_KEY")
TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN")
TWILIO_WHATSAPP_FROM = os.environ.get("TWILIO_WHATSAPP_FROM")

# ---------------------------------------------------------------------------
# Startup checks
# ---------------------------------------------------------------------------

_REQUIRED = {
    "TAVILY_API_KEY": TAVILY_API_KEY,
    "TWILIO_ACCOUNT_SID": TWILIO_ACCOUNT_SID,
    "TWILIO_AUTH_TOKEN": TWILIO_AUTH_TOKEN,
    "TWILIO_WHATSAPP_FROM": TWILIO_WHATSAPP_FROM,
}
for _var, _val in _REQUIRED.items():
    if not _val:
        raise RuntimeError(
            f"Missing required environment variable: {_var}\n"
            "Add it to your .env file and restart the server."
        )

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(title="Tech Finder Agent")

# ---------------------------------------------------------------------------
# Twilio signature verification
# ---------------------------------------------------------------------------

def _reconstruct_url(request: Request) -> str:
    proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    host = request.url.netloc
    return f"{proto}://{host}{request.url.path}"


async def _verify_twilio(request: Request) -> None:
    """Raises HTTP 403 if the request did not come from Twilio."""
    validator = RequestValidator(TWILIO_AUTH_TOKEN)
    url = _reconstruct_url(request)
    form_data = dict(await request.form())
    signature = request.headers.get("X-Twilio-Signature", "")
    if not validator.validate(url, form_data, signature):
        raise HTTPException(status_code=403, detail="Invalid Twilio signature")


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

async def _search(query: str, max_results: int = 5) -> list[dict]:
    """Search Tavily for the latest news articles on a topic."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            "https://api.tavily.com/search",
            json={
                "api_key": TAVILY_API_KEY,
                "query": query,
                "search_depth": "advanced",
                "topic": "news",        # prioritises trending news articles
                "max_results": max_results,
                "include_answer": False,
            },
        )
        response.raise_for_status()
    return response.json().get("results", [])


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------

_NUMBER_EMOJI = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣"]


def _format_results(query: str, results: list[dict]) -> str:
    if not results:
        return (
            f"😕 No recent articles found for *{query}*.\n"
            "Try rephrasing or adding a year (e.g. '2026')."
        )

    lines = [f"🔍 *Top {len(results)} results for:*\n_{query}_\n"]
    for i, r in enumerate(results[:5]):
        title = (r.get("title") or "Untitled")[:75]
        url = r.get("url", "")
        date = r.get("published_date") or ""
        date_str = f"  📅 _{date}_" if date and date != "unknown" else ""
        lines.append(f"{_NUMBER_EMOJI[i]} *{title}*{date_str}\n{url}")

    return "\n\n".join(lines)


# ---------------------------------------------------------------------------
# Twilio REST reply
# ---------------------------------------------------------------------------

async def _send_reply(to: str, body: str) -> None:
    client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
    await asyncio.to_thread(
        client.messages.create,
        from_=TWILIO_WHATSAPP_FROM,
        to=to,
        body=body,
    )


# ---------------------------------------------------------------------------
# Logging to output/
# ---------------------------------------------------------------------------

def _log_search(query: str, results: list[dict]) -> None:
    """Append search + results to a daily log file in output/."""
    try:
        log_dir = Path(__file__).parent / "output"
        log_dir.mkdir(exist_ok=True)
        log_file = log_dir / f"searches_{datetime.now().strftime('%Y-%m-%d')}.jsonl"
        entry = {
            "timestamp": datetime.now().isoformat(),
            "query": query,
            "results": [
                {"title": r.get("title"), "url": r.get("url"), "date": r.get("published_date")}
                for r in results
            ],
        }
        with log_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass  # logging is best-effort; never fail the user


# ---------------------------------------------------------------------------
# Background task
# ---------------------------------------------------------------------------

async def _handle(query: str, from_number: str) -> None:
    await _send_reply(from_number, f"🔎 Searching for *{query}*...")
    try:
        results = await _search(query)
        _log_search(query, results)
        message = _format_results(query, results)
    except Exception as exc:
        message = f"❌ Search failed: {exc}"
    await _send_reply(from_number, message)


# ---------------------------------------------------------------------------
# Webhook
# ---------------------------------------------------------------------------

@app.post("/webhook")
async def webhook(background_tasks: BackgroundTasks, request: Request):
    """
    Receives a WhatsApp message from Twilio.
    Returns empty TwiML immediately, then searches and replies in the background.
    """
    await _verify_twilio(request)
    form = dict(await request.form())
    query = (form.get("Body") or "").strip()
    from_number = form.get("From", "")

    if not query:
        # Prompt the user if they sent an empty/media-only message
        background_tasks.add_task(
            _send_reply,
            from_number,
            "👋 Send me any tech topic and I'll find the latest articles!\n\n"
            "_Examples: 'agent protocol', 'AI chip shortage 2026', 'Anthropic latest'_",
        )
    else:
        background_tasks.add_task(_handle, query, from_number)

    return Response(content="<Response/>", media_type="application/xml")


@app.get("/health")
async def health():
    return {"status": "ok", "agent": "tech-finder"}

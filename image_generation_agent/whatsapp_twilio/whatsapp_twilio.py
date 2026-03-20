"""
=============================================================================
WhatsApp Agent Hub — Twilio Sandbox + FastAPI
=============================================================================

A single FastAPI server hosting multiple WhatsApp agents. Each agent has
its own endpoint — point different Twilio numbers at different paths.

Current agents
--------------
  /webhook/image-agent   →   GPT-4o creative agent (generate images, files)

Adding a new agent
------------------
1. Create agents/<your_agent>.py with an APIRouter
2. app.include_router(your_router, prefix="/webhook/<your-agent>")
3. Point a Twilio number at https://<your-host>/webhook/<your-agent>

Key design changes vs original single-agent version
----------------------------------------------------
- Background tasks: webhook returns <Response/> instantly; agent runs async
  and replies via Twilio REST API — eliminates Twilio's 15s timeout risk.
- Multi-agent routing: each agent is an APIRouter, mounted at its own path.
- Shared Twilio signature verification: FastAPI Depends in each router.

Setup
-----
1. pip install -e ".[whatsapp]"

2. Add to .env:
       TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
       TWILIO_AUTH_TOKEN=your_auth_token_here
       TWILIO_WHATSAPP_FROM=whatsapp:+14155238886   # Twilio sandbox number
       OPENAI_API_KEY=your_openai_key_here
       FAL_KEY=your_fal_key_here

3. Run:
       uvicorn image_generation_agent.whatsapp_twilio.whatsapp_twilio:app --reload --port 8000

4. Tunnel (dev):
       ngrok http 8000

5. In Twilio sandbox console set "When a message comes in" to:
       https://<ngrok-id>.ngrok-free.app/webhook/image-agent   (HTTP POST)
=============================================================================
"""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI

# Make the repo root importable (needed by agent imports inside routers)
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

load_dotenv()

# ---------------------------------------------------------------------------
# Startup checks — fail fast if required env vars are missing
# ---------------------------------------------------------------------------

_REQUIRED_ENV = [
    "TWILIO_ACCOUNT_SID",
    "TWILIO_AUTH_TOKEN",
    "TWILIO_WHATSAPP_FROM",
    "OPENAI_API_KEY",
]
for _var in _REQUIRED_ENV:
    if not os.environ.get(_var):
        raise RuntimeError(
            f"Missing required environment variable: {_var}\n"
            "Add it to your .env file and restart the server."
        )

# ---------------------------------------------------------------------------
# Import routers (after sys.path and env are ready)
# ---------------------------------------------------------------------------

from image_generation_agent.whatsapp_twilio.agents.image_agent import router as image_router  # noqa: E402

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(title="WhatsApp Agent Hub")

# Register agents — add more here as you build them
app.include_router(image_router, prefix="/webhook/image-agent")


@app.get("/health")
async def health():
    return {"status": "ok", "agents": ["image-agent"]}

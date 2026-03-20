"""
Image generation agent — WhatsApp router.

Mounts at: /webhook/image-agent
Handles:   Generate images, save files, read files (all agent_adk_openai tools).

Background task pattern
-----------------------
Twilio has a 15-second response timeout. AI agent calls (OpenAI + fal.ai)
can easily take 5-15 seconds. To avoid timeouts:

  1. Webhook handler returns an empty TwiML <Response/> instantly.
  2. Agent runs in a FastAPI BackgroundTask.
  3. Reply is sent proactively via the Twilio REST API when the agent finishes.
"""

import asyncio
import os
import re

from fastapi import APIRouter, BackgroundTasks, Depends, Form, Request, Response
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types
from twilio.rest import Client

from image_generation_agent.whatsapp_twilio.agents.orchestrator_agent import orchestrator
from image_generation_agent.whatsapp_twilio.core.twilio_verify import verify_twilio

router = APIRouter()

# ---------------------------------------------------------------------------
# ADK session infrastructure — persistent for the life of this process.
# Each WhatsApp number gets its own session (keyed by phone number).
# ---------------------------------------------------------------------------

_APP_NAME = "whatsapp_image_agent"
_session_service = InMemorySessionService()
_runner = Runner(agent=orchestrator, app_name=_APP_NAME, session_service=_session_service)
_active_sessions: set[str] = set()


async def _ensure_session(user_id: str) -> None:
    if user_id not in _active_sessions:
        await _session_service.create_session(
            app_name=_APP_NAME,
            user_id=user_id,
            session_id=user_id,
        )
        _active_sessions.add(user_id)


async def _run_agent(message: str, user_id: str) -> str:
    await _ensure_session(user_id)
    final_response = None
    async for event in _runner.run_async(
        user_id=user_id,
        session_id=user_id,
        new_message=types.Content(
            role="user",
            parts=[types.Part(text=message)],
        ),
    ):
        if event.is_final_response() and event.content and event.content.parts:
            final_response = event.content.parts[0].text
    return final_response or "Sorry, I couldn't generate a response."


# ---------------------------------------------------------------------------
# Image URL extraction
# ---------------------------------------------------------------------------

# Matches fal.ai CDN URLs and any https URL ending in a common image extension.
_IMAGE_URL_RE = re.compile(
    r'https://(?:'
    r'fal\.media/[^\s<>"\']+'           # fal.media CDN
    r'|v3\.fal\.media/[^\s<>"\']+'      # fal v3 CDN
    r'|[^\s<>"\']+\.(?:png|jpg|jpeg|webp|gif)'  # any URL with image extension
    r')',
    re.IGNORECASE,
)


def _extract_image_urls(text: str) -> list[str]:
    """Pull image URLs out of the agent's reply text."""
    return list(dict.fromkeys(_IMAGE_URL_RE.findall(text)))  # deduplicated, order preserved


# ---------------------------------------------------------------------------
# Twilio REST client — used to send proactive replies from background tasks.
# ---------------------------------------------------------------------------

def _get_twilio_client() -> Client:
    return Client(os.environ["TWILIO_ACCOUNT_SID"], os.environ["TWILIO_AUTH_TOKEN"])


async def _send_whatsapp_reply(to: str, body: str, media_urls: list[str] | None = None) -> None:
    """
    Send a WhatsApp message via Twilio REST API.
    If media_urls are provided, Twilio downloads and attaches them as images.
    Runs the sync Twilio call in a thread to avoid blocking the event loop.
    """
    client = _get_twilio_client()
    kwargs = dict(
        from_=os.environ["TWILIO_WHATSAPP_FROM"],
        to=to,
        body=body,
    )
    if media_urls:
        kwargs["media_url"] = media_urls

    await asyncio.to_thread(client.messages.create, **kwargs)


# ---------------------------------------------------------------------------
# Background task: run agent, then reply via Twilio REST API.
# ---------------------------------------------------------------------------

async def _handle(message: str, from_number: str) -> None:
    await _send_whatsapp_reply(from_number, "Got it! Give me a moment...")
    try:
        reply = await _run_agent(message, from_number)
        image_urls = _extract_image_urls(reply)
    except Exception as exc:
        reply = f"Something went wrong: {exc}"
        image_urls = []
    await _send_whatsapp_reply(from_number, reply, media_urls=image_urls or None)


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------

@router.post("", dependencies=[Depends(verify_twilio)])
async def webhook(
    background_tasks: BackgroundTasks,
    From: str = Form(...),
    Body: str = Form(default=""),
):
    """
    Receives a WhatsApp message from Twilio, immediately returns an empty
    TwiML response (satisfying Twilio's 15s timeout), then runs the agent
    and replies via the Twilio REST API in a background task.
    """
    message = Body.strip() or "Hello! What would you like me to create?"
    background_tasks.add_task(_handle, message, From)
    return Response(content="<Response/>", media_type="application/xml")

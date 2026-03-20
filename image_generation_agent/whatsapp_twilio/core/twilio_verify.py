"""
Shared FastAPI dependency for Twilio webhook signature verification.

Import and use as:
    from image_generation_agent.whatsapp_twilio.core.twilio_verify import verify_twilio

    @router.post("", dependencies=[Depends(verify_twilio)])
    async def my_webhook(...): ...
"""

import os

from fastapi import Depends, HTTPException, Request
from twilio.request_validator import RequestValidator


def _reconstruct_url(request: Request) -> str:
    """
    Reconstruct the public-facing URL for Twilio's HMAC check.
    Reads X-Forwarded-Proto + Host so the check passes through ngrok/proxies.
    """
    proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    host = request.url.netloc  # Starlette derives this from the Host header
    return f"{proto}://{host}{request.url.path}"


async def verify_twilio(request: Request) -> None:
    """
    FastAPI dependency. Raises HTTP 403 if the request did not come from Twilio.
    Must be used on every public webhook endpoint.
    """
    validator = RequestValidator(os.environ["TWILIO_AUTH_TOKEN"])
    url = _reconstruct_url(request)
    form_data = dict(await request.form())  # Starlette caches this — safe to re-read
    signature = request.headers.get("X-Twilio-Signature", "")

    if not validator.validate(url, form_data, signature):
        raise HTTPException(status_code=403, detail="Invalid Twilio signature")

"""
=============================================================================
🤖 SAME AGENT — Built with Google ADK
=============================================================================

This file recreates the same agent from agent_guide.py using Google's
Agent Development Kit (ADK) instead of calling the Anthropic API directly.

Same tools, same behaviour — different framework.

Key differences vs the raw-API approach:
  - No manual agentic loop: ADK's Runner handles it
  - No JSON tool schemas: ADK introspects your function signatures
  - Uses Gemini 2.0 Flash natively (no LiteLLM needed)

Install:
    pip install google-adk python-dotenv httpx

Add to your .env:
    GOOGLE_API_KEY=your-google-api-key-here
    FAL_KEY=your-fal-key-here

Get a Google API key at: https://aistudio.google.com/apikey

=============================================================================
"""

import asyncio
import os
import time
from pathlib import Path

import httpx
from dotenv import load_dotenv
from google.adk.agents import Agent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

load_dotenv()


# =============================================================================
# TOOLS
# =============================================================================
# In ADK, tools are plain Python functions.
# ADK reads the function name, docstring, and type hints to build the schema
# automatically — no manual JSON schema needed.
# =============================================================================

def generate_image(prompt: str, filename: str) -> dict:
    """
    Generate an image from a text prompt and save it to the output/ folder.

    Args:
        prompt: A detailed description of the image to generate.
        filename: Filename to save the image as (e.g. 'sunset.png').

    Returns:
        A dict with status, saved filename, and the image URL.
    """
    fal_key = os.environ.get("FAL_KEY")
    if not fal_key:
        return {
            "error": "FAL_KEY not set.",
            "tip": "Get a key at https://fal.ai/dashboard/keys",
        }

    try:
        response = httpx.post(
            "https://queue.fal.run/fal-ai/flux/schnell",
            headers={
                "Authorization": f"Key {fal_key}",
                "Content-Type": "application/json",
            },
            json={
                "prompt": prompt,
                "image_size": "landscape_4_3",
                "num_images": 1,
                "enable_safety_checker": True,
            },
            timeout=120.0,
        )
        response.raise_for_status()
        queue = response.json()

        # fal.ai queue endpoint is async — poll until COMPLETED
        status_url = queue["status_url"]
        response_url = queue["response_url"]

        while True:
            status = httpx.get(
                status_url,
                headers={"Authorization": f"Key {fal_key}"},
                timeout=30.0,
            ).json()
            if status["status"] == "COMPLETED":
                break
            if status["status"] == "FAILED":
                return {"error": "fal.ai generation failed"}
            time.sleep(2)

        result = httpx.get(
            response_url,
            headers={"Authorization": f"Key {fal_key}"},
            timeout=30.0,
        ).json()
        image_url = result["images"][0]["url"]

        images_dir = Path(__file__).parent / "output"
        images_dir.mkdir(exist_ok=True)
        save_path = images_dir / filename
        image_data = httpx.get(image_url, timeout=60.0).content
        save_path.write_bytes(image_data)

        return {
            "status": "success",
            "filename": str(save_path),
            "url": image_url,
            "prompt_used": prompt,
        }

    except Exception as e:
        return {"error": str(e)}


def save_file(filename: str, content: str) -> dict:
    """
    Save text content to a file on disk.

    Args:
        filename: The filename to save to.
        content: The text content to write.

    Returns:
        A dict with status and bytes written.
    """
    try:
        Path(filename).write_text(content)
        return {"status": "success", "filename": filename, "bytes_written": len(content)}
    except Exception as e:
        return {"error": str(e)}


def read_file(filename: str) -> dict:
    """
    Read the contents of a file from disk.

    Args:
        filename: The filename to read.

    Returns:
        A dict with status and file content.
    """
    try:
        content = Path(filename).read_text()
        return {"status": "success", "filename": filename, "content": content}
    except FileNotFoundError:
        return {"error": f"File '{filename}' not found"}
    except Exception as e:
        return {"error": str(e)}


# =============================================================================
# AGENT
# =============================================================================
# Pass the tool functions directly — ADK wraps them automatically.
# =============================================================================

root_agent = Agent(
    name="creative_assistant",
    model="gemini-2.0-flash",
    description="A creative assistant that can generate images and manage files.",
    instruction=(
        "You are a helpful creative assistant. When the user asks you to "
        "generate or create an image, use the generate_image tool with a "
        "detailed, descriptive prompt. Always confirm what you created."
    ),
    tools=[generate_image, save_file, read_file],
)


# =============================================================================
# RUNNER
# =============================================================================

async def run_agent(user_message: str, session_id: str = "default-session"):
    """Run the agent and return the final response text."""

    session_service = InMemorySessionService()
    session = await session_service.create_session(
        app_name="creative_agent",
        user_id="user",
        session_id=session_id,
    )

    runner = Runner(
        agent=root_agent,
        app_name="creative_agent",
        session_service=session_service,
    )

    print(f"\n🧑 User: {user_message}")
    print("─" * 60)

    final_response = None
    async for event in runner.run_async(
        user_id="user",
        session_id=session.id,
        new_message=types.Content(
            role="user",
            parts=[types.Part(text=user_message)],
        ),
    ):
        if event.is_final_response() and event.content and event.content.parts:
            final_response = event.content.parts[0].text

    if final_response:
        print(f"\n🤖 Agent: {final_response}")
        print("\n✅ Done!")
    return final_response


# =============================================================================
# RUN IT
# =============================================================================

if __name__ == "__main__":
    if not os.environ.get("GOOGLE_API_KEY"):
        print("❌ GOOGLE_API_KEY not found!")
        print("   Add to .env: GOOGLE_API_KEY=your-key-here")
        print("   Get a key at: https://aistudio.google.com/apikey")
        exit(1)

    if not os.environ.get("FAL_KEY"):
        print("⚠️  FAL_KEY not found — image generation won't work.")
        print("   Add to .env: FAL_KEY=your-fal-key-here\n")

    # --- Example 1: Generate an image ---
    asyncio.run(run_agent(
        "Generate an image of a cozy coffee shop on a rainy evening, "
        "with warm lighting coming through the windows. Save it as coffee_shop.png"
    ))

    # --- Example 2: Multi-step task ---
    # asyncio.run(run_agent(
    #     "Generate an image of a mountain landscape at sunset, save it as "
    #     "mountains.png, then write a haiku about it and save to haiku.txt"
    # ))

"""
=============================================================================
🤖 BUILD YOUR OWN CLAUDE AGENT — Complete Guide
=============================================================================

This file teaches you the CORE PATTERN for building an agent with Claude.
An agent = Claude + Tools + A Loop that keeps going until the task is done.

We'll build an agent that can:
  1. Generate images (via fal.ai)
  2. Search the web
  3. Save files to disk

The same pattern works for ANY tool you want to add.

=============================================================================
ARCHITECTURE OVERVIEW
=============================================================================

    ┌──────────────────────────────────────────────┐
    │                YOUR AGENT                     │
    │                                               │
    │   User Prompt ──► Claude API ──► Response      │
    │                      │                        │
    │              Does Claude want                  │
    │              to use a tool?                    │
    │                 /        \                     │
    │               YES         NO                  │
    │               │            │                   │
    │         Execute tool    Return final           │
    │         locally         response to user       │
    │               │                                │
    │         Send result                            │
    │         back to Claude                         │
    │               │                                │
    │         (Loop continues)                       │
    └──────────────────────────────────────────────┘

=============================================================================
"""

import anthropic
import json
import base64
import httpx
import os
import time
from pathlib import Path
from dotenv import load_dotenv

# =============================================================================
# Load environment variables from .env file
# =============================================================================
# This looks for a file called ".env" in the same folder as this script.
# It reads the key=value pairs and loads them into os.environ so your
# code can access them via os.environ.get("KEY_NAME").
#
# Your .env file should look like this (NO quotes needed around values):
#
#   ANTHROPIC_API_KEY=sk-ant-api03-xxxxxxxxxxxx
#   FAL_KEY=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
#
# =============================================================================
load_dotenv()  # <-- This one line does all the magic


# =============================================================================
# STEP 1: DEFINE YOUR TOOLS
# =============================================================================
# Tools are just Python functions + a JSON schema that tells Claude what
# the tool does and what arguments it takes. Claude reads the schema and
# decides WHEN and HOW to call each tool.
#
# KEY INSIGHT: Claude never executes tools itself. It returns a "tool_use"
# message saying "I want to call X with these args." YOUR code executes
# the tool and sends the result back.
# =============================================================================

# --- Tool Definitions (JSON Schemas for Claude) ---

TOOLS = [
    {
        "name": "generate_image",
        "description": (
            "Generate an image from a text prompt using an AI image generation model. "
            "Use this when the user asks you to create, generate, draw, or make an image. "
            "Returns the image as a base64-encoded string and saves it to disk."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "A detailed description of the image to generate. Be specific about style, colors, composition, etc."
                },
                "filename": {
                    "type": "string",
                    "description": "Filename to save the image as (e.g., 'sunset.png')"
                }
            },
            "required": ["prompt", "filename"]
        }
    },
    {
        "name": "save_file",
        "description": "Save text content to a file on disk.",
        "input_schema": {
            "type": "object",
            "properties": {
                "filename": {
                    "type": "string",
                    "description": "The filename to save to"
                },
                "content": {
                    "type": "string",
                    "description": "The text content to write"
                }
            },
            "required": ["filename", "content"]
        }
    },
    {
        "name": "read_file",
        "description": "Read the contents of a file from disk.",
        "input_schema": {
            "type": "object",
            "properties": {
                "filename": {
                    "type": "string",
                    "description": "The filename to read"
                }
            },
            "required": ["filename"]
        }
    }
]


# =============================================================================
# STEP 2: IMPLEMENT YOUR TOOL FUNCTIONS
# =============================================================================
# Each tool name maps to an actual Python function that does the work.
# These run locally on YOUR machine, not on Anthropic's servers.
# =============================================================================

def generate_image(prompt: str, filename: str) -> str:
    """
    Generate an image using fal.ai's API.

    You could swap this for ANY image generation API:
      - fal.ai (recommended — you already use it!)
      - OpenAI DALL-E
      - Stability AI
      - Replicate
      - A local Stable Diffusion instance

    The agent pattern stays EXACTLY the same regardless of which API you use.
    """
    FAL_API_KEY = os.environ.get("FAL_KEY")

    if not FAL_API_KEY:
        return json.dumps({
            "error": "FAL_KEY not set. Set it with: export FAL_KEY='your-key-here'",
            "tip": "Get a key at https://fal.ai/dashboard/keys"
        })

    # --- Option A: fal.ai (your preferred tool) ---
    try:
        response = httpx.post(
            "https://queue.fal.run/fal-ai/flux/schnell",  # Fast model
            headers={
                "Authorization": f"Key {FAL_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "prompt": prompt,
                "image_size": "landscape_4_3",
                "num_images": 1,
                "enable_safety_checker": True
            },
            timeout=120.0
        )
        response.raise_for_status()
        queue = response.json()

        # fal.ai queue endpoint is async — poll until COMPLETED
        status_url = queue["status_url"]
        response_url = queue["response_url"]

        while True:
            status = httpx.get(
                status_url,
                headers={"Authorization": f"Key {FAL_API_KEY}"},
                timeout=30.0,
            ).json()
            if status["status"] == "COMPLETED":
                break
            if status["status"] == "FAILED":
                return json.dumps({"error": "fal.ai generation failed"})
            time.sleep(2)

        result = httpx.get(
            response_url,
            headers={"Authorization": f"Key {FAL_API_KEY}"},
            timeout=30.0,
        ).json()
        image_url = result["images"][0]["url"]

        # Download and save the image to the output/ folder
        images_dir = Path(__file__).parent / "output"
        images_dir.mkdir(exist_ok=True)
        save_path = images_dir / filename
        image_data = httpx.get(image_url, timeout=60.0).content
        save_path.write_bytes(image_data)

        return json.dumps({
            "status": "success",
            "filename": str(save_path),
            "url": image_url,
            "prompt_used": prompt
        })

    except Exception as e:
        return json.dumps({"error": str(e)})


def save_file(filename: str, content: str) -> str:
    """Save text content to a file."""
    try:
        Path(filename).write_text(content)
        return json.dumps({"status": "success", "filename": filename, "bytes_written": len(content)})
    except Exception as e:
        return json.dumps({"error": str(e)})


def read_file(filename: str) -> str:
    """Read a file's contents."""
    try:
        content = Path(filename).read_text()
        return json.dumps({"status": "success", "filename": filename, "content": content})
    except FileNotFoundError:
        return json.dumps({"error": f"File '{filename}' not found"})
    except Exception as e:
        return json.dumps({"error": str(e)})


# --- Tool Registry: Maps tool names to functions ---
TOOL_HANDLERS = {
    "generate_image": lambda args: generate_image(args["prompt"], args["filename"]),
    "save_file": lambda args: save_file(args["filename"], args["content"]),
    "read_file": lambda args: read_file(args["filename"]),
}


# =============================================================================
# STEP 3: THE AGENTIC LOOP ⭐ (This is the core pattern!)
# =============================================================================
# This is the heart of every agent. The loop:
#   1. Sends the conversation to Claude
#   2. Checks if Claude wants to use any tools
#   3. If yes → execute tools, send results back, go to step 1
#   4. If no  → return Claude's final text response
#
# This pattern is IDENTICAL whether you're building:
#   - An image generation agent
#   - A code review agent
#   - A data analysis agent
#   - A customer support agent
# =============================================================================

def run_agent(user_message: str, system_prompt: str = None, max_iterations: int = 10):
    """
    Run the agentic loop.

    Args:
        user_message: What the user wants
        system_prompt: Optional personality/instructions for the agent
        max_iterations: Safety limit to prevent infinite loops
    """

    client = anthropic.Anthropic()  # Uses ANTHROPIC_API_KEY env var

    # Default system prompt if none provided
    if system_prompt is None:
        system_prompt = (
            "You are a helpful creative assistant. When the user asks you to "
            "generate or create an image, use the generate_image tool with a "
            "detailed, descriptive prompt. Always confirm what you created."
        )

    # Conversation history — this grows as the agent works
    messages = [
        {"role": "user", "content": user_message}
    ]

    print(f"\n🧑 User: {user_message}")
    print("─" * 60)

    for iteration in range(max_iterations):
        print(f"\n🔄 Agent Loop — Iteration {iteration + 1}")

        # ── Call Claude ──────────────────────────────────────────
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=4096,
            system=system_prompt,
            tools=TOOLS,
            messages=messages
        )

        print(f"   Stop reason: {response.stop_reason}")

        # ── Process the response ─────────────────────────────────
        # Claude's response can contain MULTIPLE content blocks:
        #   - TextBlock: Claude's text/thinking
        #   - ToolUseBlock: Claude wants to call a tool

        assistant_content = response.content

        # Print any text blocks
        for block in assistant_content:
            if block.type == "text":
                print(f"\n🤖 Claude: {block.text}")

        # ── Check: Is Claude done, or does it want to use tools? ──
        if response.stop_reason == "end_turn":
            # Claude is done! No more tools needed.
            print("\n✅ Agent finished!")
            final_text = " ".join(
                block.text for block in assistant_content
                if block.type == "text"
            )
            return final_text

        elif response.stop_reason == "tool_use":
            # Claude wants to use one or more tools.
            # We need to:
            #   1. Add Claude's response to the conversation
            #   2. Execute each tool
            #   3. Add tool results to the conversation
            #   4. Loop back to call Claude again

            # Add Claude's full response (including tool_use blocks)
            messages.append({"role": "assistant", "content": assistant_content})

            # Execute each tool request
            tool_results = []
            for block in assistant_content:
                if block.type == "tool_use":
                    tool_name = block.name
                    tool_input = block.input
                    tool_use_id = block.id

                    print(f"\n   🔧 Tool call: {tool_name}")
                    print(f"      Input: {json.dumps(tool_input, indent=2)[:200]}")

                    # Execute the tool
                    if tool_name in TOOL_HANDLERS:
                        result = TOOL_HANDLERS[tool_name](tool_input)
                    else:
                        result = json.dumps({"error": f"Unknown tool: {tool_name}"})

                    print(f"      Result: {result[:200]}...")

                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tool_use_id,
                        "content": result
                    })

            # Add ALL tool results as a single user message
            messages.append({"role": "user", "content": tool_results})

        else:
            print(f"⚠️  Unexpected stop reason: {response.stop_reason}")
            break

    print("\n⚠️  Hit max iterations — stopping.")
    return None


# =============================================================================
# STEP 4: RUN IT!
# =============================================================================

if __name__ == "__main__":
    # --- Verify keys are loaded ---
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("❌ ANTHROPIC_API_KEY not found!")
        print("   Create a .env file in this folder with:")
        print("   ANTHROPIC_API_KEY=sk-ant-your-key-here")
        exit(1)

    if not os.environ.get("FAL_KEY"):
        print("⚠️  FAL_KEY not found — image generation won't work.")
        print("   Add to .env: FAL_KEY=your-fal-key-here")
        print("   (Continuing anyway — other tools still work)\n")

    print("✅ Keys loaded from .env!")
    print(f"   ANTHROPIC_API_KEY: {os.environ['ANTHROPIC_API_KEY'][:12]}...")
    if os.environ.get("FAL_KEY"):
        print(f"   FAL_KEY: {os.environ['FAL_KEY'][:8]}...")

    # --- Example 1: Generate an image ---
    result = run_agent(
        "Generate an image of a cozy coffee shop on a rainy evening, "
        "with warm lighting coming through the windows. Save it as coffee_shop.png"
    )

    # --- Example 2: Multi-step task (Claude will chain tools) ---
    # result = run_agent(
    #     "Generate an image of a mountain landscape at sunset, save it as "
    #     "mountains.png, then write a haiku about it and save to haiku.txt"
    # )

    # --- Example 3: Custom system prompt ---
    # result = run_agent(
    #     "Create a logo for a startup called 'RentMyAgent'",
    #     system_prompt=(
    #         "You are a creative director at a design agency. When asked to "
    #         "create images, write extremely detailed prompts that specify "
    #         "style, colors, typography approach, and composition. Always "
    #         "generate multiple concepts if the task is a logo."
    #     )
    # )


# =============================================================================
# STEP 5: HOW TO ADD YOUR OWN TOOLS
# =============================================================================
#
# Adding a new tool is always the same 3 steps:
#
#   1. ADD THE SCHEMA to the TOOLS list:
#      {
#          "name": "your_tool_name",
#          "description": "What it does (Claude reads this!)",
#          "input_schema": { ... JSON Schema ... }
#      }
#
#   2. WRITE THE FUNCTION:
#      def your_tool_name(arg1, arg2) -> str:
#          # Do the thing
#          return json.dumps({"result": "..."})
#
#   3. REGISTER IT in TOOL_HANDLERS:
#      TOOL_HANDLERS["your_tool_name"] = lambda args: your_tool_name(args["arg1"], args["arg2"])
#
# That's it. Claude automatically decides when to call your tool
# based on the description you provide.
#
# =============================================================================
#
# EXAMPLE: Adding a "text_to_speech" tool:
#
#   Schema:
#     {
#         "name": "text_to_speech",
#         "description": "Convert text to speech audio using ElevenLabs API",
#         "input_schema": {
#             "type": "object",
#             "properties": {
#                 "text": {"type": "string", "description": "Text to speak"},
#                 "voice": {"type": "string", "description": "Voice ID to use"}
#             },
#             "required": ["text"]
#         }
#     }
#
#   Function:
#     def text_to_speech(text, voice="default"):
#         response = httpx.post("https://api.elevenlabs.io/v1/text-to-speech/...", ...)
#         Path("output.mp3").write_bytes(response.content)
#         return json.dumps({"status": "success", "file": "output.mp3"})
#
#   Register:
#     TOOL_HANDLERS["text_to_speech"] = lambda a: text_to_speech(a["text"], a.get("voice", "default"))
#
# =============================================================================


# =============================================================================
# BONUS: THE THREE TIERS OF BUILDING AGENTS WITH CLAUDE
# =============================================================================
#
# ┌─────────────────────────────────────────────────────────────────┐
# │  TIER 1: Raw API + Tool Use (THIS FILE)                        │
# │  ─────────────────────────────────────                          │
# │  • You control the loop                                         │
# │  • You define and execute tools                                 │
# │  • Maximum flexibility                                          │
# │  • Best for: Custom agents, production systems, learning        │
# │  • pip install anthropic                                        │
# ├─────────────────────────────────────────────────────────────────┤
# │  TIER 2: Claude Agent SDK                                       │
# │  ────────────────────────                                       │
# │  • SDK manages the loop for you                                 │
# │  • Built-in tools (Bash, Read, Write, Edit, WebSearch)          │
# │  • Custom tools via MCP servers                                 │
# │  • Best for: Dev tools, CLI agents, code-related tasks          │
# │  • pip install claude-agent-sdk                                 │
# │                                                                 │
# │  Example:                                                       │
# │    from claude_agent_sdk import query, ClaudeAgentOptions        │
# │    async for msg in query(                                       │
# │        prompt="Find and fix bugs in my code",                    │
# │        options=ClaudeAgentOptions(                                │
# │            allowed_tools=["Read", "Edit", "Bash"],               │
# │            permission_mode="acceptEdits"                         │
# │        )                                                         │
# │    ):                                                            │
# │        print(msg)                                                │
# ├─────────────────────────────────────────────────────────────────┤
# │  TIER 3: MCP (Model Context Protocol)                           │
# │  ───────────────────────────────────                             │
# │  • Standardized tool servers anyone can build/share              │
# │  • Claude auto-discovers tools from connected servers            │
# │  • Best for: Ecosystem integrations (Slack, GitHub, etc.)        │
# │  • Works with both Tier 1 and Tier 2                             │
# └─────────────────────────────────────────────────────────────────┘
#
# For YOUR use case (image gen agent):
#   → Start with Tier 1 (this file) for full control
#   → Graduate to Tier 2 if you want built-in Bash/file tools
#   → Add MCP servers for ecosystem integrations
#
# =============================================================================

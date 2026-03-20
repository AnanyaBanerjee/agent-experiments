"""
=============================================================================
📰 TECH NEWSLETTER RESEARCH AGENT — The Tech Blueprint
=============================================================================

This agent researches a tech topic and drafts a full newsletter issue in the
style of "The Tech Blueprint" — authoritative, analytical, no-fluff writing
for tech professionals and entrepreneurs.

Flow:
  1. Takes a topic from the user (CLI or WhatsApp)
  2. Searches for recent articles using Tavily
  3. Fetches and reads the most relevant articles
  4. Synthesises findings into a structured newsletter draft
  5. Saves the draft as a .md file in output/
  6. (WhatsApp mode) Sends the draft back to the user via Twilio

Tools:
  - search_web:    find recent articles via Tavily REST API
  - fetch_article: read full article content via httpx
  - save_draft:    write the finished draft to output/

CLI usage:
    pip install -e ".[newsletter]"
    python tech_newsletter_agent/agent_tech_newsletter/agent_tech_newsletter.py

WhatsApp usage:
    pip install -e ".[newsletter]"
    uvicorn tech_newsletter_agent.agent_tech_newsletter.agent_tech_newsletter:app --reload --port 8002
    ngrok http 8002
    # Set Twilio webhook → https://<ngrok-id>.ngrok-free.app/webhook  (POST)
    # Text the sandbox: "create newsletter on AI agents"

Add to your .env:
    ANTHROPIC_API_KEY=your-anthropic-api-key-here
    TAVILY_API_KEY=your-tavily-api-key-here
    TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
    TWILIO_AUTH_TOKEN=your-twilio-auth-token-here
    TWILIO_WHATSAPP_FROM=whatsapp:+14155238886

=============================================================================
"""

import asyncio
import json
import os
import re
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path

import anthropic
import httpx
from dotenv import load_dotenv

load_dotenv()

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
TAVILY_API_KEY = os.environ.get("TAVILY_API_KEY")

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

# =============================================================================
# HTML → PLAIN TEXT EXTRACTOR
# =============================================================================
# Strips script/style/nav tags and returns readable article text.
# Uses Python's built-in html.parser — no extra dependencies.
# =============================================================================

class _HTMLTextExtractor(HTMLParser):
    _SKIP_TAGS = {"script", "style", "nav", "header", "footer", "aside", "noscript"}

    def __init__(self):
        super().__init__()
        self._parts = []
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in self._SKIP_TAGS:
            self._skip_depth += 1

    def handle_endtag(self, tag):
        if tag in self._SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1

    def handle_data(self, data):
        if self._skip_depth == 0:
            stripped = data.strip()
            if stripped:
                self._parts.append(stripped)

    def get_text(self) -> str:
        return " ".join(self._parts)


def _html_to_text(html: str) -> str:
    extractor = _HTMLTextExtractor()
    extractor.feed(html)
    return extractor.get_text()


# =============================================================================
# TOOLS
# =============================================================================

def search_web(query: str, max_results: int = 5) -> dict:
    """
    Search for recent articles on a topic using Tavily.

    Args:
        query: Search query. Include 'latest' or the current year for recency.
        max_results: Number of results to return (1–10).

    Returns:
        A dict with a list of results, each containing title, url, snippet,
        and published_date.
    """
    if not TAVILY_API_KEY:
        return {
            "error": "TAVILY_API_KEY not set.",
            "tip": "Get a free key at https://tavily.com",
        }

    try:
        response = httpx.post(
            "https://api.tavily.com/search",
            json={
                "api_key": TAVILY_API_KEY,
                "query": query,
                "search_depth": "advanced",
                "max_results": max_results,
                "include_answer": False,
                "include_raw_content": False,
            },
            timeout=30.0,
        )
        response.raise_for_status()
        data = response.json()

        results = [
            {
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "snippet": r.get("content", ""),
                "published_date": r.get("published_date", "unknown"),
            }
            for r in data.get("results", [])
        ]

        return {"status": "success", "query": query, "results": results}

    except Exception as e:
        return {"error": str(e)}


def fetch_article(url: str) -> dict:
    """
    Fetch and extract readable text content from an article URL.

    Args:
        url: The article URL to fetch.

    Returns:
        A dict with the extracted text content (truncated to 4000 chars).
    """
    try:
        response = httpx.get(
            url,
            headers={"User-Agent": "Mozilla/5.0 (compatible; TechNewsletterBot/1.0)"},
            timeout=20.0,
            follow_redirects=True,
        )
        response.raise_for_status()

        text = _html_to_text(response.text)
        # Truncate to keep token usage manageable while preserving key content
        if len(text) > 4000:
            text = text[:4000] + "... [truncated]"

        return {"status": "success", "url": url, "content": text}

    except Exception as e:
        return {"error": str(e), "url": url}


def save_draft(filename: str, content: str) -> dict:
    """
    Save the newsletter draft to the output/ folder.

    Args:
        filename: Filename for the draft, e.g. 'issue_ai_agents_2026.md'.
        content: Full newsletter content in Markdown format.

    Returns:
        A dict with the saved file path and byte count.
    """
    try:
        output_dir = Path(__file__).parent / "output"
        output_dir.mkdir(exist_ok=True)
        save_path = output_dir / filename
        save_path.write_text(content, encoding="utf-8")
        return {
            "status": "success",
            "path": str(save_path),
            "bytes_written": len(content.encode("utf-8")),
        }
    except Exception as e:
        return {"error": str(e)}


# =============================================================================
# TOOL SCHEMAS
# =============================================================================

TOOLS = [
    {
        "name": "search_web",
        "description": (
            "Search for recent articles and news on a topic using Tavily. "
            "Use this first to discover relevant sources. Run 1–2 searches "
            "to cover different angles of the topic."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": (
                        "The search query. Be specific. Include the year "
                        "(e.g. '2026') or 'latest' for recent results."
                    ),
                },
                "max_results": {
                    "type": "integer",
                    "description": "Number of results to return. Default 5.",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "fetch_article",
        "description": (
            "Fetch and read the full text of a specific article URL. "
            "Use this on the 2–3 most relevant results from search_web "
            "to get depth before writing."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "The URL of the article to read.",
                },
            },
            "required": ["url"],
        },
    },
    {
        "name": "save_draft",
        "description": "Save the completed newsletter draft as a Markdown file.",
        "input_schema": {
            "type": "object",
            "properties": {
                "filename": {
                    "type": "string",
                    "description": (
                        "Descriptive filename, e.g. 'issue_ai_agents_march_2026.md'. "
                        "Always use .md extension."
                    ),
                },
                "content": {
                    "type": "string",
                    "description": "The full newsletter draft in Markdown format.",
                },
            },
            "required": ["filename", "content"],
        },
    },
]

TOOL_HANDLERS = {
    "search_web": lambda args: search_web(args["query"], args.get("max_results", 5)),
    "fetch_article": lambda args: fetch_article(args["url"]),
    "save_draft": lambda args: save_draft(args["filename"], args["content"]),
}

# =============================================================================
# SYSTEM PROMPT
# =============================================================================

SYSTEM_PROMPT = f"""You are the writer for "The Tech Blueprint" — a weekly AI and tech newsletter by Ananya Banerjee.

TODAY'S DATE: {datetime.now().strftime("%B %d, %Y")}

## Research Process
1. Search for the most sensational and high-impact AI, tech, and robotics news from this week
2. Run search_web("most sensational AI tech breakthroughs news {datetime.now().strftime('%B %Y')}", max_results=8)
3. Run search_web("biggest robotics startup tech announcements {datetime.now().strftime('%B %Y')}", max_results=6)
4. Pick 4 distinct stories — one per section (Transformational / Educational / Creativity / Hi-Tech)
5. Call fetch_article(url) on each of the 4 story URLs for full content
6. Write the complete newsletter in the EXACT FORMAT below
7. Save with save_draft() using filename "issue_{datetime.now().strftime('%Y_%m_%d')}.md"

## Exact Newsletter Format (follow precisely — this is the real format of The Tech Blueprint)

# [Catchy headline naming 2-3 of this week's biggest stories]

*Let's talk about this week's latest news from around the world.*

---

**Welcome to The Tech Blueprint!**
In today's Tech and AI updates:

[emoji] [Story A full headline]
[emoji] [Story B full headline]
[emoji] [Story C full headline]
[emoji] [Story D full headline]

Read Time: 5 minutes

[2-3 sentence engaging intro — conversational, warm, sets context for the week]

Now, Let's begin by focusing on 4 pieces of news that were most noteworthy this week!

---

## 🌎 Transformational News 🖊️
*Updates from around the world that have the potential to change the world*

[1-2 sentence scene-setter]

**What is the news?**
[2-4 clear sentences explaining what happened]

**Why should you care?**
[3-5 bullet points — significance, broader impact, who is affected]

**Where and How can you use it?**
[3-5 bullet points — practical applications for engineers, entrepreneurs, everyday people]

---

## ☄️ Educational News 📚
*Learning Medium, Productivity Hacks, etc that help you evolve to the next version of yourself.*

**What is the news?**
[Key facts as bullet points — what it is, who made it, what it does]

**Why should you care?**
[3-5 bullet points — value and significance for readers]

**How can you use it?**
[3-5 bullet points — practical use cases for developers, researchers, businesses, creators]

---

## 💥 Creativity Corner 🗡️
*Creative Use of Technology that can touch lives!*

**What is the news?**
[Clear explanation of the creative tech story]

**Why should you care?**
[2-4 sentences or bullet points on why this matters for creators and designers]

**Where and How can you use it?**
[3-5 bullet points — where to access it, what to build with it, who benefits]

---

## 🤖 Hi-Tech News 📌
*The latest updates in AI and Tech from around the globe.*

**What is the news?**
[Key facts — use bullet points for features, benchmarks, specs]

**Why should you care?**
[3-4 sentences or bullets on significance in the AI/tech landscape]

**Where and How can you use it?**
[3-5 bullet points — how practitioners and businesses can apply or prepare for this]

---

## 🔮 Magical Productivity Hack 🔮
*The productivity hack of the week*

**What is [Name of a real, well-known theory or framework]?**
[2-3 sentences explaining the theory/framework]

**How do I apply it?**

[Principle 1 — named]: [brief explanation]
Action: [one specific concrete step]

[Principle 2 — named]: [brief explanation]
Action: [one specific concrete step]

[Principle 3 — named]: [brief explanation]
Action: [one specific concrete step]

[Principle 4 — named]: [brief explanation]
Action: [one specific concrete step]

[Principle 5 — named]: [brief explanation]
Action: [one specific concrete step]

[1-2 sentence closing tying the hack to the reader's goals]

---

*That's it for today, but don't forget to subscribe so it's delivered straight to your inbox every week.*

👋 Follow me for the latest updates in Tech and AI. 🔔

🔥 Subscribe to **The Tech Blueprint™** — Join thousands of subscribers who kick-start their Tuesdays with the week's hottest tech updates, actionable productivity hacks, and brand-amplifying tips.

## Writing Rules
- Friendly and conversational, not corporate or stiff
- Short paragraphs (2-4 sentences max)
- Use bold for key terms
- Each story section: 150-250 words
- Productivity hack: 200-300 words
- Total: ~900-1200 words (5 minutes read time)
- Always use real news from search results — never fabricate stories"""

# =============================================================================
# AGENTIC LOOP
# =============================================================================

def _run_loop(messages: list, max_iter: int = 20) -> str:
    """Run the agentic tool loop until end_turn. Returns the final text."""
    for _ in range(max_iter):
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=messages,
        )

        if response.stop_reason == "end_turn":
            return next((b.text for b in response.content if hasattr(b, "text")), "")

        if response.stop_reason == "tool_use":
            messages.append({"role": "assistant", "content": response.content})
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    preview = {k: v for k, v in block.input.items() if k != "content"}
                    print(f"  🔧 {block.name}({json.dumps(preview)[:100]})")
                    result = TOOL_HANDLERS[block.name](block.input)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps(result),
                    })
            messages.append({"role": "user", "content": tool_results})

    return "Reached max iterations without completing."


def run_agent(topic: str) -> str:
    """
    Research this week's top stories and produce a newsletter draft.
    Runs interactively in CLI: shows story shortlist, waits for confirmation,
    shows draft, then allows up to 5 edit rounds before saving.
    """
    print(f"\n📰 The Tech Blueprint — {datetime.now().strftime('%B %d, %Y')}")
    print("─" * 60)

    messages = [
        {
            "role": "user",
            "content": (
                f"Find this week's most sensational AI, tech and robotics news "
                f"and prepare a story shortlist for The Tech Blueprint newsletter. "
                f"Context from user: {topic}"
                if topic else
                "Find this week's most sensational AI, tech and robotics news "
                "and prepare a story shortlist for The Tech Blueprint newsletter."
            ),
        }
    ]

    # Phase 1 & 2: story discovery + confirmation loop
    while True:
        reply = _run_loop(messages, max_iter=15)
        print(f"\n{reply}\n")
        messages.append({"role": "assistant", "content": reply})

        user_input = input("You: ").strip()
        if not user_input:
            continue
        messages.append({"role": "user", "content": user_input})

        # If user confirmed, move to draft phase
        confirmed = any(w in user_input.lower() for w in ["yes", "ok", "good", "great", "go", "proceed", "write", "draft"])
        if confirmed:
            break

    # Phase 3: write the newsletter
    print("\n✍️  Writing your newsletter...\n")
    draft_reply = _run_loop(messages, max_iter=20)
    print(f"\n{draft_reply}\n")
    messages.append({"role": "assistant", "content": draft_reply})

    # Phase 4: edit loop (max 5 rounds)
    for edit_num in range(1, 6):
        user_input = input("You (or press Enter to save): ").strip()
        if not user_input:
            break
        done = any(w in user_input.lower() for w in ["save", "done", "finalize", "looks good", "perfect", "publish"])
        if done:
            break

        messages.append({"role": "user", "content": user_input})
        print(f"\n✏️  Applying edits ({edit_num}/5)...\n")
        reply = _run_loop(messages, max_iter=15)
        print(f"\n{reply}\n")
        messages.append({"role": "assistant", "content": reply})

        if edit_num == 5:
            print("📌 Edit limit (5/5) reached — saving current version.")

    # Phase 5: save
    messages.append({"role": "user", "content": "Save the newsletter now."})
    final = _run_loop(messages, max_iter=10)
    print(f"\n{final}\n")
    print("✅ Done!\n")
    return final


# =============================================================================
# WHATSAPP WEBHOOK (FastAPI)
# =============================================================================
# Run with:
#   uvicorn tech_newsletter_agent.agent_tech_newsletter.agent_tech_newsletter:app \
#     --reload --port 8002
# =============================================================================

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request, Response
from twilio.request_validator import RequestValidator
from twilio.rest import Client

TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN")
TWILIO_WHATSAPP_FROM = os.environ.get("TWILIO_WHATSAPP_FROM")

app = FastAPI(title="Tech Newsletter Agent")

# ---------------------------------------------------------------------------
# Twilio helpers
# ---------------------------------------------------------------------------

def _reconstruct_url(request: Request) -> str:
    proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    return f"{proto}://{request.url.netloc}{request.url.path}"


async def _verify_twilio(request: Request) -> None:
    """Raises HTTP 403 if the request did not come from Twilio."""
    if not TWILIO_AUTH_TOKEN:
        return  # skip verification if Twilio not configured
    validator = RequestValidator(TWILIO_AUTH_TOKEN)
    url = _reconstruct_url(request)
    form_data = dict(await request.form())
    signature = request.headers.get("X-Twilio-Signature", "")
    if not validator.validate(url, form_data, signature):
        raise HTTPException(status_code=403, detail="Invalid Twilio signature")


async def _send_reply(to: str, body: str) -> None:
    twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
    await asyncio.to_thread(
        twilio_client.messages.create,
        from_=TWILIO_WHATSAPP_FROM,
        to=to,
        body=body,
    )


# ---------------------------------------------------------------------------
# Topic parsing
# ---------------------------------------------------------------------------

def _parse_topic(message: str) -> str | None:
    """Extract the newsletter topic from a WhatsApp message.

    Handles patterns like:
      "create newsletter on AI agents"
      "newsletter about quantum computing"
      "draft a newsletter for LLM fine-tuning"
      "newsletter: robotics in 2026"
    """
    msg = message.strip()
    patterns = [
        r"(?:create|write|draft|make)\s+(?:a\s+)?newsletter\s+(?:on|about|for|covering)\s+(.+)",
        r"newsletter\s+(?:on|about|for|covering)\s+(.+)",
        r"newsletter[:\-]\s*(.+)",
    ]
    for pattern in patterns:
        m = re.search(pattern, msg, re.IGNORECASE)
        if m:
            return m.group(1).strip().rstrip(".")

    # "newsletter" appears somewhere — grab everything after it
    lower = msg.lower()
    if "newsletter" in lower:
        idx = lower.index("newsletter") + len("newsletter")
        remainder = msg[idx:].strip().lstrip(":,.– -").strip()
        if remainder:
            return remainder

    return None


# ---------------------------------------------------------------------------
# Message splitting (WhatsApp max ~1600 chars per message)
# ---------------------------------------------------------------------------

def _split_message(text: str, max_len: int = 1500) -> list[str]:
    if len(text) <= max_len:
        return [text]
    chunks: list[str] = []
    while text:
        if len(text) <= max_len:
            chunks.append(text)
            break
        split_at = text.rfind("\n", 0, max_len)
        if split_at == -1:
            split_at = max_len
        chunks.append(text[:split_at])
        text = text[split_at:].lstrip("\n")
    return chunks


# ---------------------------------------------------------------------------
# Background task
# ---------------------------------------------------------------------------

async def _handle_newsletter(topic: str, from_number: str) -> None:
    await _send_reply(
        from_number,
        f"📝 Researching and drafting your newsletter on *{topic}*...\n"
        "_This takes about 30–60 seconds — I'll send it over when it's ready._",
    )
    try:
        # run_agent is synchronous — run it in a thread pool
        await asyncio.to_thread(run_agent, topic)

        # Read back the most recently saved draft
        output_dir = Path(__file__).parent / "output"
        drafts = sorted(
            output_dir.glob("*.md"),
            key=lambda f: f.stat().st_mtime,
            reverse=True,
        )
        if not drafts:
            await _send_reply(from_number, "✅ Newsletter drafted and saved to the output folder.")
            return

        content = drafts[0].read_text(encoding="utf-8")
        chunks = _split_message(content)
        total = len(chunks)
        for i, chunk in enumerate(chunks, 1):
            header = f"📰 *Newsletter ({i}/{total})*\n\n" if total > 1 else ""
            await _send_reply(from_number, header + chunk)

    except Exception as exc:
        await _send_reply(from_number, f"❌ Newsletter generation failed: {exc}")


# ---------------------------------------------------------------------------
# Webhook
# ---------------------------------------------------------------------------

@app.post("/webhook")
async def webhook(background_tasks: BackgroundTasks, request: Request):
    """
    Receives a WhatsApp message from Twilio.
    Returns empty TwiML immediately, then drafts the newsletter in the background.
    """
    await _verify_twilio(request)
    form = dict(await request.form())
    body = (form.get("Body") or "").strip()
    from_number = form.get("From", "")

    topic = _parse_topic(body)

    if not topic:
        background_tasks.add_task(
            _send_reply,
            from_number,
            "👋 Send me a newsletter topic and I'll research and draft it for you!\n\n"
            "_Examples:_\n"
            "• _'create newsletter on AI agents'_\n"
            "• _'newsletter about quantum computing 2026'_\n"
            "• _'draft newsletter on LLM fine-tuning'_",
        )
    else:
        background_tasks.add_task(_handle_newsletter, topic, from_number)

    return Response(content="<Response/>", media_type="application/xml")


@app.get("/health")
async def health():
    return {"status": "ok", "agent": "tech-newsletter"}


# =============================================================================
# CLI ENTRYPOINT
# =============================================================================

if __name__ == "__main__":
    if not ANTHROPIC_API_KEY:
        print("❌ ANTHROPIC_API_KEY not found in .env")
        exit(1)
    if not TAVILY_API_KEY:
        print("❌ TAVILY_API_KEY not found in .env")
        print("   Get a free key at: https://tavily.com")
        exit(1)

    topic = input("Topic or focus (press Enter for this week's top stories): ").strip()
    run_agent(topic)

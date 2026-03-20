"""
=============================================================================
🎨 CREATIVE HUB — ADK Multi-Agent Router (A2A)
=============================================================================

Handles image generation, prompt writing, tech newsletters, news search,
and Notion bookmarking. Speaks the A2A protocol — works with AgentChat
(iOS/Android/Web) and any other A2A-compatible client.

  User says...                              → Agent triggered
  ─────────────────────────────────────────────────────────────────────────
  "generate an image of a sunset"          → image_agent
  "write me a prompt for a neon city"      → prompt_agent
  "create newsletter on AI agents"         → newsletter_agent
  "find latest news on OpenAI"             → tech_finder_agent
  Share a URL + "save this"               → content_saver_agent
  Anything else                            → router answers directly

Architecture:
  ┌─────────────────────────────────────────────────────┐
  │  Router Agent  (LlmAgent, sub_agents)               │
  │   ├─ image_agent      (AgentTool: prompt + gen)     │
  │   │   ├─ prompt_specialist  (LlmAgent, no tools)    │
  │   │   └─ image_generator    (LlmAgent, fal.ai tool) │
  │   ├─ prompt_agent     (LlmAgent, no tools)          │
  │   ├─ newsletter_agent (LlmAgent, web search + save) │
  │   ├─ tech_finder_agent  (LlmAgent, web search)      │
  │   └─ content_saver_agent(LlmAgent, Notion API)      │
  └─────────────────────────────────────────────────────┘

  A2A endpoints (served by shared.a2a_server):
    GET  /.well-known/agent.json   — agent card discovery
    POST /a2a                      — JSON-RPC 2.0 (stream + send)
    GET  /health                   — liveness check

Setup:
  pip install -e ".[hub]"
  uvicorn whatsapp_hub.agent_whatsapp_hub.agent_whatsapp_hub:app --reload --port 8000
=============================================================================
"""

import os
import re
import time
import json
import base64
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse

import anthropic
import httpx
from dotenv import load_dotenv

from google.adk.agents import LlmAgent
from google.adk.models.lite_llm import LiteLlm
from google.adk.tools.agent_tool import AgentTool

from shared.a2a_server import create_hub_app

load_dotenv()

# ─── Environment ──────────────────────────────────────────────────────────────

FAL_KEY = os.environ.get("FAL_KEY", "")
NOTION_API_KEY = os.environ.get("NOTION_API_KEY", "")
NOTION_DATABASE_ID = os.environ.get("NOTION_DATABASE_ID", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

OUTPUT_DIR = Path(__file__).parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

_MODEL = LiteLlm(model="anthropic/claude-sonnet-4-6")


# ─── Status update stub ───────────────────────────────────────────────────────
# A2A hubs use SSE streaming for progress visibility — no external push needed.
# This stub keeps all agent instructions unchanged while being a no-op.

def send_status_update(message: str) -> dict:
    """
    No-op stub for A2A hubs. Progress is conveyed via SSE task state transitions
    (submitted → working → completed) rather than push messages.

    Args:
        message: Status message (logged but not sent anywhere).

    Returns:
        dict with status "skipped".
    """
    return {"status": "skipped", "message": message}


# ─── TOOL FUNCTIONS ───────────────────────────────────────────────────────────

# ── Image generation (fal.ai Flux Schnell) ────────────────────────────────────

def generate_image(prompt: str, filename: str = "") -> dict:
    """
    Generate an image from a text prompt using fal.ai Flux Schnell.

    Args:
        prompt: Detailed description of the image to generate.
        filename: Output filename (e.g. 'sunset.png'). Auto-generated if empty.

    Returns:
        dict with image_url and saved_path on success, or error message.
    """
    if not FAL_KEY:
        return {"error": "FAL_KEY not configured in .env"}

    if not filename:
        slug = re.sub(r"[^a-z0-9]+", "_", prompt.lower())[:40].strip("_")
        filename = f"{slug}.png"

    headers = {"Authorization": f"Key {FAL_KEY}", "Content-Type": "application/json"}

    with httpx.Client(timeout=30.0) as client:
        resp = client.post(
            "https://queue.fal.run/fal-ai/flux/schnell",
            headers=headers,
            json={"prompt": prompt, "num_images": 1, "image_size": "landscape_4_3"},
        )
        resp.raise_for_status()
        job = resp.json()

        for _ in range(30):
            time.sleep(3)
            status = client.get(job["status_url"], headers=headers, timeout=10.0)
            if status.json().get("status") == "COMPLETED":
                break

        result_resp = client.get(job["response_url"], headers=headers, timeout=15.0)
        result_resp.raise_for_status()

    images = result_resp.json().get("images", [])
    if not images:
        return {"error": "No images returned from fal.ai"}

    image_url = images[0]["url"]

    with httpx.Client(timeout=30.0) as client:
        img_data = client.get(image_url)
        img_data.raise_for_status()

    save_path = OUTPUT_DIR / filename
    save_path.write_bytes(img_data.content)

    return {"image_url": image_url, "saved_path": str(save_path), "filename": filename}


# ── Web search (Claude native) ────────────────────────────────────────────────

def _claude_search(prompt: str, max_tokens: int = 1500) -> str:
    """Call Claude with its native web_search tool and return the final text response."""
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=max_tokens,
        tools=[{"type": "web_search_20250305", "name": "web_search"}],
        messages=[{"role": "user", "content": prompt}],
    )
    return "".join(
        block.text for block in response.content if hasattr(block, "text")
    ).strip()


def search_news(query: str) -> dict:
    """
    Search for the 5 most recent news articles on a topic using Claude web search.

    Args:
        query: Tech topic to search for (e.g. 'OpenAI GPT-5 2026').

    Returns:
        dict with a 'message' key containing formatted results.
    """
    text = _claude_search(
        f"Search for the 5 most recent news articles about: {query}\n\n"
        "Format your response exactly like this (use real URLs and dates from search results):\n"
        "🔍 *Top 5 results for:*\n"
        f"_{query}_\n\n"
        "1️⃣ *Article Title Here*  📅 _2026-03-19_\n"
        "https://actual-url.com/article\n\n"
        "2️⃣ *Another Article Title*  📅 _2026-03-18_\n"
        "https://another-url.com/article\n\n"
        "Continue for all 5 results.",
        max_tokens=1500,
    )
    return {"message": text, "query": query}


def search_web(query: str, max_results: int = 5) -> dict:
    """
    Search for recent articles for newsletter research using Claude web search.

    Args:
        query: Search query — include year or 'latest' for recent results.
        max_results: Number of results (1–10, default 5).

    Returns:
        dict with 'content' key containing titles, URLs, dates, and summaries.
    """
    text = _claude_search(
        f"Search for {max_results} high-quality recent articles about: {query}\n\n"
        "For each result provide: title, URL, publication date, and a 2-sentence summary. "
        "Focus on in-depth articles suitable for newsletter research.",
        max_tokens=2000,
    )
    return {"status": "success", "query": query, "content": text}


# ── Newsletter tools ───────────────────────────────────────────────────────────

class _HTMLStripper(HTMLParser):
    _SKIP = {"script", "style", "nav", "header", "footer", "aside", "noscript"}

    def __init__(self):
        super().__init__()
        self._parts: list[str] = []
        self._depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in self._SKIP:
            self._depth += 1

    def handle_endtag(self, tag):
        if tag in self._SKIP and self._depth > 0:
            self._depth -= 1

    def handle_data(self, data):
        if self._depth == 0 and data.strip():
            self._parts.append(data.strip())

    def text(self) -> str:
        return " ".join(self._parts)


def fetch_article(url: str) -> dict:
    """
    Fetch and extract readable text from an article URL.

    Args:
        url: Article URL to fetch.

    Returns:
        dict with extracted article text, truncated to 4000 chars.
    """
    try:
        resp = httpx.get(
            url,
            headers={"User-Agent": "Mozilla/5.0 (compatible; NewsletterBot/1.0)"},
            timeout=20.0,
            follow_redirects=True,
        )
        resp.raise_for_status()
        stripper = _HTMLStripper()
        stripper.feed(resp.text)
        text = stripper.text()
        if len(text) > 4000:
            text = text[:4000] + "... [truncated]"
        return {"status": "success", "url": url, "content": text}
    except Exception as e:
        return {"error": str(e), "url": url}


def save_newsletter_draft(filename: str, content: str) -> dict:
    """
    Save the completed newsletter draft as a Markdown file.

    Args:
        filename: e.g. 'issue_ai_agents_march_2026.md' (.md extension required).
        content: Full newsletter content in Markdown format.

    Returns:
        dict with saved path and byte count.
    """
    if not filename.endswith(".md"):
        filename += ".md"
    save_path = OUTPUT_DIR / filename
    save_path.write_text(content, encoding="utf-8")
    return {
        "status": "success",
        "path": str(save_path),
        "bytes_written": len(content.encode()),
    }


# ── Notion saver tools ────────────────────────────────────────────────────────

def extract_page_content(url: str) -> dict:
    """
    Fetch a URL and extract its title, main text, and source domain.

    Args:
        url: The URL to fetch and read.

    Returns:
        dict with title, content (≤3000 chars), domain, and url.
    """
    domain = urlparse(url).netloc.replace("www.", "")
    try:
        resp = httpx.get(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                )
            },
            timeout=15.0,
            follow_redirects=True,
        )
        resp.raise_for_status()

        title_match = re.search(r"<title[^>]*>([^<]+)</title>", resp.text, re.IGNORECASE)
        raw_title = title_match.group(1).strip() if title_match else ""
        title = re.split(r"\s*[|\-–]\s*[A-Z]", raw_title)[0].strip() or raw_title

        stripper = _HTMLStripper()
        stripper.feed(resp.text)
        text = stripper.text()
        if len(text) > 3000:
            text = text[:3000] + "... [truncated]"

        if len(text) < 200:
            text = f"[Content could not be extracted — page may require JavaScript]\nTitle: {title}\nURL: {url}"

        return {"title": title, "content": text, "domain": domain, "url": url}
    except httpx.TimeoutException:
        return {
            "title": "",
            "content": f"[Page timed out — could not fetch content]\nURL: {url}",
            "domain": domain,
            "url": url,
            "note": "Proceed to save using just the URL and domain.",
        }
    except Exception as e:
        return {
            "title": "",
            "content": f"[Could not fetch page: {e}]\nURL: {url}",
            "domain": domain,
            "url": url,
            "note": "Proceed to save using just the URL and domain.",
        }


def analyze_image_content(image_base64: str, mime_type: str = "image/jpeg") -> dict:
    """
    Analyze an image with Claude vision.
    Returns a suggested title, category, summary, and tags.

    Args:
        image_base64: Base64-encoded image data.
        mime_type: MIME type of the image (e.g. 'image/jpeg', 'image/png').

    Returns:
        dict with title, category, summary, tags extracted from the image.
    """
    if not ANTHROPIC_API_KEY:
        return {"error": "ANTHROPIC_API_KEY not configured"}

    vision_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    result = vision_client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=600,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {"type": "base64", "media_type": mime_type, "data": image_base64},
                },
                {
                    "type": "text",
                    "text": (
                        "Analyze this image and respond with JSON only:\n"
                        '{"title": "descriptive title (max 80 chars)", '
                        '"category": "one of: Article, Research, Tutorial, Tool, Social Post, Image, News, Video, Other", '
                        '"summary": "2-sentence description of what this is", '
                        '"tags": ["tag1", "tag2", "tag3"]}'
                    ),
                },
            ],
        }],
    )

    raw = result.content[0].text
    try:
        json_match = re.search(r"\{.*\}", raw, re.DOTALL)
        if json_match:
            return json.loads(json_match.group())
    except Exception:
        pass
    return {"title": "Image", "category": "Image", "summary": raw[:200], "tags": []}


def save_to_notion(
    title: str,
    category: str,
    summary: str,
    tags: list,
    url: str = "",
    source: str = "",
) -> dict:
    """
    Save content to the user's Notion workspace database.

    Args:
        title: Title of the content (max 100 chars).
        category: One of: Article, Research, Tutorial, Tool, Social Post, Image, News, Video, Other.
        summary: Brief description (2-3 sentences).
        tags: List of relevant topic tags (e.g. ["AI", "LLM", "Python"]).
        url: Source URL (optional).
        source: Domain or source name (e.g. "techcrunch.com").

    Returns:
        dict with notion_page_url on success, or error.
    """
    if not NOTION_API_KEY or not NOTION_DATABASE_ID:
        return {"error": "NOTION_API_KEY or NOTION_DATABASE_ID not configured in .env"}

    properties: dict = {
        "Name": {"title": [{"text": {"content": title[:100]}}]},
        "Category": {"select": {"name": category}},
        "Summary": {"rich_text": [{"text": {"content": summary[:2000]}}]},
        "Tags": {"multi_select": [{"name": t.strip()[:50]} for t in (tags or [])[:10]]},
        "Date Added": {"date": {"start": datetime.now().strftime("%Y-%m-%d")}},
    }
    if url:
        properties["URL"] = {"url": url}
    if source:
        properties["Source"] = {"rich_text": [{"text": {"content": source[:200]}}]}

    resp = httpx.post(
        "https://api.notion.com/v1/pages",
        headers={
            "Authorization": f"Bearer {NOTION_API_KEY}",
            "Notion-Version": "2022-06-28",
            "Content-Type": "application/json",
        },
        json={"parent": {"database_id": NOTION_DATABASE_ID}, "properties": properties},
        timeout=15.0,
    )
    resp.raise_for_status()
    page = resp.json()
    return {
        "status": "saved",
        "notion_url": page.get("url", ""),
        "title": title,
        "category": category,
    }


# ─── ADK AGENTS ───────────────────────────────────────────────────────────────

# ── Agent 1: Prompt Specialist ────────────────────────────────────────────────

prompt_specialist = LlmAgent(
    name="prompt_specialist",
    model=_MODEL,
    description="Writes and refines detailed Flux Schnell image generation prompts.",
    instruction="""You are an expert at writing detailed image generation prompts for Flux Schnell AI.

When given an image idea, produce a single detailed prompt covering:
- Subject: specific description of the main subject
- Setting: environment, background, lighting, time of day
- Style: photorealistic, oil painting, concept art, illustration, etc.
- Mood and atmosphere
- Composition and perspective
- Quality keywords: highly detailed, sharp focus, 8k resolution

When given refinement feedback alongside a previous prompt, incorporate the changes
while keeping what worked well.

Return ONLY the prompt text — no labels, no explanations, no extra commentary.""",
    tools=[],
)

# ── Agent 2: Image Generator ──────────────────────────────────────────────────

image_generator = LlmAgent(
    name="image_generator",
    model=_MODEL,
    description="Generates images using fal.ai given an approved prompt.",
    instruction="""You generate images using the generate_image tool.

When given a prompt:
1. Call send_status_update("🎨 Generating your image with fal.ai — this takes ~30 seconds...")
2. Choose a short descriptive filename in snake_case (e.g. 'sunset_beach.png')
3. Call generate_image with the exact prompt and your chosen filename
4. Return the full result including image_url

Use the prompt exactly as given — do not modify it.""",
    tools=[generate_image, send_status_update],
)

# ── Agent 3: Image Agent (conversational: prompt → approve → generate) ────────

image_agent = LlmAgent(
    name="image_agent",
    model=_MODEL,
    description="Conversational image creation: writes a detailed prompt, shows it for user approval, then generates the image on approval.",
    instruction="""You manage a conversational image creation workflow.

WORKFLOW — follow these rules exactly:

1. USER REQUESTS AN IMAGE:
   - Call send_status_update("✍️ Writing your image prompt...")
   - Call prompt_specialist with their idea to generate a detailed prompt.
   - Send the prompt in this exact format:

     Here's your image prompt:

     ──────────────────────────────
     [prompt text here]
     ──────────────────────────────

     Reply *yes* to generate this image, or tell me what you'd like to change.
     Round 1/5

2. USER APPROVES (says yes / ok / looks good / generate it / go ahead / perfect):
   - Call image_generator with the approved prompt.
   - After the image is generated and the URL is returned, send:
     "✅ Done! Here's your image. What else can I help you with?"
   - Then transfer back to the main router for the next request.

3. USER WANTS CHANGES (any feedback about the prompt):
   - Call prompt_specialist again with: original idea + previous prompt + user's feedback.
   - Show the refined prompt in the same formatted block.
   - Increment the round counter (Round 2/5, Round 3/5, etc.)

4. ROUND LIMIT REACHED (after round 5):
   - Do NOT call prompt_specialist again.
   - Tell the user they've reached the maximum 5 refinement rounds.
   - Show the current prompt and ask: approve it or start fresh?

5. USER STARTS A NEW REQUEST mid-conversation:
   - Reset to round 1 and treat as a fresh image request.

NEVER call image_generator without explicit user approval.
After completing an image or if the user asks for something different, transfer back to router.""",
    tools=[
        AgentTool(agent=prompt_specialist),
        AgentTool(agent=image_generator),
        send_status_update,
    ],
)

# ── Agent 4: Prompt Agent (standalone prompt writing, no image generation) ────

prompt_agent = LlmAgent(
    name="prompt_agent",
    model=_MODEL,
    description="Writes detailed Flux Schnell image generation prompts without generating the image.",
    instruction="""You write detailed, evocative image generation prompts for Flux Schnell AI.

Start by calling send_status_update("✍️ Crafting your Flux Schnell prompt...")

When given an image idea, produce a detailed prompt covering:
- Subject: specific description of the main subject
- Setting: environment, background, lighting, time of day
- Style: art style or medium (photorealistic, oil painting, anime, concept art, etc.)
- Mood and atmosphere
- Composition, perspective, and framing
- Quality keywords: highly detailed, sharp focus, 8k resolution

Format your response:

📝 *Your Flux Schnell Prompt:*
──────────────────────────────
[prompt text here]
──────────────────────────────

Then ask: "Would you like me to refine this, or shall I pass it to the image agent to generate it?"

If the user wants to generate: tell them to say "generate an image" with their idea.
If they want refinements: incorporate the feedback and show the revised prompt.
After completing, transfer back to router.""",
    tools=[send_status_update],
)

# ── Agent 5: Tech Finder Agent ────────────────────────────────────────────────

tech_finder_agent = LlmAgent(
    name="tech_finder_agent",
    model=_MODEL,
    description="Searches for and returns the top 5 latest news articles on a tech topic.",
    instruction="""You find the latest news articles on the user's topic.

1. Call send_status_update("🔍 Searching the web for the latest news...")
2. Call search_news with the topic as the query.
3. Return the formatted 'message' from the tool result directly — do not reformat it.
4. After delivering the results, ask "What else can I help you with?"
5. Then transfer back to router.""",
    tools=[search_news, send_status_update],
)

# ── Agent 6: Newsletter Agent ──────────────────────────────────────────────────

_NEWSLETTER_INSTRUCTION = f"""You are the writer for "The Tech Blueprint" — a weekly AI and tech newsletter by Ananya Banerjee.

TODAY'S DATE: {datetime.now().strftime("%B %d, %Y")}

=============================================================
MULTI-PHASE WORKFLOW — read conversation history to determine which phase you are in
=============================================================

PHASE 1 — FIND THIS WEEK'S NEWS (enter this phase when the user first requests a newsletter):
1. Call send_status_update("🔍 Scanning for this week's most sensational AI, tech & robotics stories...")
2. Call search_web("most sensational AI artificial intelligence news breakthroughs this week {datetime.now().strftime('%B %Y')}", max_results=8)
3. Call search_web("biggest robotics tech startup announcements {datetime.now().strftime('%B %Y')}", max_results=6)
4. Pick 4 distinct high-impact stories — one per section:
   - Story A → 🌎 Transformational News: tech that changes the world (major product launches, policy, paradigm shifts)
   - Story B → ☄️ Educational News: tools, papers, frameworks, learning resources that help people grow
   - Story C → 💥 Creativity Corner: creative or artistic use of technology, design tools, novel applications
   - Story D → 🤖 Hi-Tech News: core AI/ML/robotics advances, model releases, hardware
5. Present the shortlist to the user in this exact format:

📰 *Here are this week's top stories for The Tech Blueprint:*

🌎 *Transformational:* [Story A headline] — [1-line summary]
☄️ *Educational:* [Story B headline] — [1-line summary]
💥 *Creativity:* [Story C headline] — [1-line summary]
🤖 *Hi-Tech:* [Story D headline] — [1-line summary]

Do these look good? Reply *yes* to write the newsletter, or tell me which story to swap.

---

PHASE 2 — STORY CONFIRMATION (enter when user responds to the shortlist above):
- If user approves (yes / looks good / go ahead / perfect) → proceed to PHASE 3
- If user asks to swap a story → call search_web for a replacement on that topic, pick the best one, show the updated shortlist again

---

PHASE 3 — WRITE THE NEWSLETTER (enter after user confirms stories):
1. Call send_status_update("📖 Reading the articles in depth...")
2. Call fetch_article(url) on each of the 4 story URLs
3. Call send_status_update("✍️ Writing your Tech Blueprint newsletter...")
4. Write the complete newsletter using THE EXACT FORMAT defined below
5. Do NOT save yet — present the draft to the user:

   Here's your newsletter draft! ✏️ *Edit 0/5*
   Reply with any changes you'd like, or say *save* to finalize it.

---

PHASE 4 — EDITING LOOP (enter when user gives feedback on a draft):
- Count previous "Edit X/5" messages in history to track current edit number
- Apply the user's requested changes to the newsletter
- Re-send the full updated draft labelled ✏️ *Edit 1/5*, *Edit 2/5*, etc.
- If user says save / done / finalize / looks good / perfect → go to PHASE 5
- At Edit 5/5: auto-save the current version and tell the user

---

PHASE 5 — SAVE (enter when user approves or edit limit reached):
1. Call save_newsletter_draft("issue_{datetime.now().strftime('%Y_%m_%d')}.md", [full newsletter text])
2. Reply: "✅ Newsletter saved! Great issue 🎉"
3. Transfer back to router.

=============================================================
THE TECH BLUEPRINT — EXACT NEWSLETTER FORMAT (follow precisely)
=============================================================

# [Catchy headline that names 2-3 of this week's biggest stories]

*Let's talk about this week's latest news from around the world.*

---

**Welcome to The Tech Blueprint!**
In today's Tech and AI updates:

[emoji] [Story A full headline]
[emoji] [Story B full headline]
[emoji] [Story C full headline]
[emoji] [Story D full headline]

Read Time: 5 minutes

[2-3 sentence engaging intro that sets the context for this week — conversational, warm, not formal]

Now, Let's begin by focusing on 4 pieces of news that were most noteworthy this week!

---

## 🌎 Transformational News 🖊️
*Updates from around the world that have the potential to change the world*

[1-2 sentence scene-setter about this story]

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
[Clear explanation of the creative tech story — what was made/released]

**Why should you care?**
[2-4 sentences or bullet points on why this matters for creators, designers, or builders]

**Where and How can you use it?**
[3-5 bullet points — where to access it, what to build with it, who benefits]

---

## 🤖 Hi-Tech News 📌
*The latest updates in AI and Tech from around the globe.*

**What is the news?**
[Key facts — can use bullet points for features, benchmarks, specs]

**Why should you care?**
[3-4 sentences or bullets on its significance in the AI/tech landscape]

**Where and How can you use it?**
[3-5 bullet points — how practitioners and businesses can apply or prepare for this]

---

## 🔮 Magical Productivity Hack 🔮
*The productivity hack of the week*

**What is [Name of a real, well-known theory or framework]?**
[2-3 sentences explaining the theory/framework clearly]

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

[1-2 sentence closing that connects the hack to the reader's goals]

---

*That's it for today, but don't forget to subscribe so it's delivered straight to your inbox every week.*

👋 Follow me for the latest updates in Tech and AI. 🔔

🔥 Subscribe to **The Tech Blueprint™** — Join thousands of subscribers who kick-start their Tuesdays with the week's hottest tech updates, actionable productivity hacks, and brand-amplifying tips.

=============================================================
WRITING RULES
=============================================================
- Friendly and conversational, not corporate or stiff
- Short paragraphs (2-4 sentences max)
- Use bold for key terms
- Each story section: 150-250 words
- Productivity hack section: 200-300 words
- Total newsletter: ~900-1200 words (about 5 minutes reading time)
- Always use real news from your search results — never fabricate stories or URLs"""

newsletter_agent = LlmAgent(
    name="newsletter_agent",
    model=_MODEL,
    description="Researches a tech topic and drafts a full newsletter issue in The Tech Blueprint style.",
    instruction=_NEWSLETTER_INSTRUCTION,
    tools=[search_web, fetch_article, save_newsletter_draft, send_status_update],
)

# ── Agent 7: Notion Content Saver ─────────────────────────────────────────────

content_saver_agent = LlmAgent(
    name="content_saver_agent",
    model=_MODEL,
    description="Saves shared URLs and images to the user's Notion workspace with smart categorisation.",
    instruction="""You save articles, links, and images to the user's Notion workspace.

You receive messages that may contain:
- A plain URL (e.g. "https://techcrunch.com/...")
- A URL with a caption (e.g. "save this https://...")
- A base64 image part from the A2A message

WORKFLOW:

1. DETERMINE WHAT WAS SHARED and immediately call send_status_update:
   - If the message contains image data → call send_status_update("🖼️ Analysing your image with Claude vision...") then analyze_image_content(base64, mime_type)
   - If the message contains an https:// URL → call send_status_update("🔗 Reading the article...") then extract_page_content(URL)

2. ANALYSE the content returned by the tool — ALWAYS proceed even if content is thin:
   - For URLs: use title, content, domain to decide category/summary/tags
   - For images: use title, category, summary, tags from analyze_image_content
   - If extraction failed, infer from URL structure (youtube.com → Video, arxiv.org → Research)

3. Call send_status_update("💾 Saving to Notion...") then call save_to_notion with all fields.
   Do NOT stop or ask the user — always proceed to save.

4. REPLY to the user:
   "✅ Saved to Notion!
   📌 *[title]*
   📂 Category: [category]
   🏷️ Tags: [tags]
   🔗 [notion_url]"

5. Ask: "What else can I help you with?" then transfer back to router.

Category guide:
- Blog posts, news → Article
- Academic papers → Research
- Step-by-step guides → Tutorial
- Apps, developer tools → Tool
- Tweets, LinkedIn → Social Post
- YouTube → Video

NEVER give up after extract_page_content fails — always proceed to save_to_notion.""",
    tools=[extract_page_content, analyze_image_content, save_to_notion, send_status_update],
)

# ── Root Router ───────────────────────────────────────────────────────────────

router_agent = LlmAgent(
    name="router",
    model=_MODEL,
    description="Routes messages to the right specialist agent.",
    instruction="""You are an AI assistant that routes user requests to the right specialist agent.

ROUTING — transfer immediately, no clarifying questions needed:

| User intent                                                          | Transfer to           |
|----------------------------------------------------------------------|-----------------------|
| Generate / create / draw / make an image                             | image_agent           |
| Write / generate a prompt (without generating the image)             | prompt_agent          |
| Create / write / draft a newsletter                                  | newsletter_agent      |
| Find / search news / latest articles / links on a topic              | tech_finder_agent     |
| Save / bookmark / store a URL or image                               | content_saver_agent   |
| Anything else (general questions, explanations, advice)              | Answer directly       |

When a user first messages, greet them briefly:
"👋 Hi! I'm your Creative Hub. I can help you with:
🖼️ *Image generation* — _'generate an image of a sunset'_
✍️ *Prompt writing* — _'write me a prompt for a neon city'_
📰 *Tech newsletter* — _'create newsletter on AI agents'_
🔍 *News search* — _'find latest news on OpenAI'_
💾 *Save to Notion* — _share any link and say 'save this'_"

Then route immediately based on their request.""",
    sub_agents=[image_agent, prompt_agent, newsletter_agent, tech_finder_agent, content_saver_agent],
)

# ─── FastAPI App (A2A) ────────────────────────────────────────────────────────

_AGENT_CARD = {
    "name": "Ananya's Creative Hub",
    "description": (
        "Your creative AI assistant: generate images, write Flux Schnell prompts, "
        "draft tech newsletters, find the latest AI/tech news, and save content to Notion."
    ),
    "version": "2.0.0",
    "capabilities": {
        "streaming": True,
        "pushNotifications": False,
    },
    "skills": [
        {
            "id": "image_generation",
            "name": "Image Generation",
            "description": "Generate images from text prompts using fal.ai Flux Schnell. Shows you the prompt first for approval, then generates.",
            "tags": ["image", "ai art", "flux", "generation"],
            "examples": [
                "Generate an image of a futuristic city at sunset",
                "Create an image of a robot reading a book",
            ],
        },
        {
            "id": "prompt_writing",
            "name": "Prompt Writing",
            "description": "Write detailed, optimised Flux Schnell image generation prompts without generating the image.",
            "tags": ["prompt", "image", "flux", "writing"],
            "examples": [
                "Write me a prompt for a neon cyberpunk street scene",
                "Write a prompt for a watercolour portrait of a fox",
            ],
        },
        {
            "id": "tech_newsletter",
            "name": "Tech Newsletter",
            "description": "Finds this week's most sensational AI/tech/robotics news, confirms with you, then drafts a full Tech Blueprint newsletter.",
            "tags": ["newsletter", "tech", "AI", "writing", "research"],
            "examples": [
                "Create a newsletter",
                "Draft this week's tech newsletter",
            ],
        },
        {
            "id": "tech_news",
            "name": "Tech News Finder",
            "description": "Find the top 5 latest news articles on any AI or tech topic.",
            "tags": ["news", "search", "AI", "tech", "robotics"],
            "examples": [
                "Find latest news on OpenAI",
                "What's happening with humanoid robots this week?",
            ],
        },
        {
            "id": "notion_saver",
            "name": "Save to Notion",
            "description": "Save any article URL or image to your Notion workspace with smart categorisation and tags.",
            "tags": ["notion", "save", "bookmark", "article"],
            "examples": [
                "Save this https://techcrunch.com/...",
                "Bookmark this article for me",
            ],
        },
    ],
    "defaultInputModes": ["text/plain"],
    "defaultOutputModes": ["text/plain"],
}

app = create_hub_app(
    app_name="creative_hub",
    agent_card=_AGENT_CARD,
    root_agent=router_agent,
)

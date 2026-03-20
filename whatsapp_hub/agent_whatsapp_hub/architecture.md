# agent_whatsapp_hub — Architecture

> **Framework:** Google ADK &nbsp;|&nbsp; **Model:** Claude Sonnet 4.6 (via LiteLLM) &nbsp;|&nbsp; **Interface:** WhatsApp (Twilio) + Mobile App (A2A) &nbsp;|&nbsp; **Deployed on:** Railway

A single server hosts all agents behind two interfaces: WhatsApp (Twilio) and any A2A-compatible mobile app. The ADK router classifies the user's intent and transfers control to the right sub-agent, which handles the full task — including multi-turn flows — before transferring back.

---

## High-Level Architecture

```mermaid
flowchart TD
    WA([📱 WhatsApp])
    MB([📱 Mobile App\nExpo / A2A Client])
    Twilio[☁️ Twilio]

    subgraph Railway Server
        Webhook[POST /webhook\nTwilio interface]
        A2AEndpoint[POST /a2a\nA2A interface]
        AgentCard[GET /.well-known/agent.json\nAgent Card]
        BG[BackgroundTask\n_handle&#40;&#41;]
        Router[🤖 Router Agent\nLlmAgent + sub_agents]

        ImageAgent[🖼️ image_agent]
        PromptAgent[✍️ prompt_agent]
        NewsletterAgent[📰 newsletter_agent]
        TechFinderAgent[🔍 tech_finder_agent]
        ContentSaverAgent[💾 content_saver_agent]
    end

    FalAI[☁️ fal.ai\nFlux Schnell]
    ClaudeSearch[☁️ Claude\nWeb Search]
    Notion[☁️ Notion API]
    Output[📁 output/\nimages + drafts]

    WA -->|message| Twilio
    Twilio -->|POST form| Webhook
    Webhook -->|200 instantly| Twilio
    Webhook --> BG
    BG --> Router

    MB -->|GET| AgentCard
    MB -->|POST JSON-RPC| A2AEndpoint
    A2AEndpoint --> Router
    A2AEndpoint -->|SSE stream| MB

    Router -->|transfer| ImageAgent
    Router -->|transfer| PromptAgent
    Router -->|transfer| NewsletterAgent
    Router -->|transfer| TechFinderAgent
    Router -->|transfer| ContentSaverAgent

    ImageAgent -->|generate_image| FalAI
    FalAI --> Output

    NewsletterAgent -->|search_web| ClaudeSearch
    NewsletterAgent -->|fetch_article| ClaudeSearch
    NewsletterAgent -->|save_newsletter_draft| Output

    TechFinderAgent -->|search_news| ClaudeSearch
    ContentSaverAgent -->|extract_page_content| ClaudeSearch
    ContentSaverAgent -->|analyze_image_content| ClaudeSearch
    ContentSaverAgent -->|save_to_notion| Notion

    BG -->|Twilio REST API| Twilio
    Twilio --> WA
```

---

## Dual Interface Design

The same Railway server handles two clients simultaneously with no conflict:

| Interface | Endpoint | Client | Response pattern |
|---|---|---|---|
| WhatsApp | `POST /webhook` | Twilio sandbox | Return `<Response/>` instantly, reply via Twilio REST API in background |
| Mobile App | `POST /a2a` | Expo app (A2A protocol) | Stream SSE events: `submitted → working → completed` |
| Discovery | `GET /.well-known/agent.json` | Expo app | Returns Agent Card JSON describing all 5 skills |

Both interfaces call the same `_run_agent(message, user_id)` function — the routing and agent logic is identical regardless of which client sent the message.

---

## Routing Logic

The **Router Agent** receives every message and transfers to the right specialist:

| User says… | Routed to |
|---|---|
| "generate an image of…" | `image_agent` |
| "write me a prompt for…" | `prompt_agent` |
| "create a newsletter" / "draft newsletter" | `newsletter_agent` |
| "find latest news on…" | `tech_finder_agent` |
| "save this https://…" / shares a link or image | `content_saver_agent` |
| General questions | Router answers directly |

---

## The Five Sub-Agents

### 1. Image Agent (`image_agent`)

Conversational image creation with human-in-the-loop prompt approval (max 5 refinement rounds).

```mermaid
sequenceDiagram
    participant U as User
    participant IA as image_agent
    participant PS as prompt_specialist
    participant IG as image_generator
    participant F as fal.ai

    U->>IA: "generate an image of a sunset"
    IA->>PS: AgentTool(idea)
    PS-->>IA: detailed Flux Schnell prompt
    IA->>U: prompt block + "Reply yes to generate — Round 1/5"
    U->>IA: "make it more dramatic"
    IA->>PS: AgentTool(idea + feedback)
    PS-->>IA: refined prompt
    IA->>U: refined prompt block — Round 2/5
    U->>IA: "yes"
    IA->>IG: AgentTool(approved prompt)
    IG->>F: generate_image(prompt, filename)
    F-->>IG: image_url
    IG-->>IA: {image_url, saved_path}
    IA->>U: "✅ Done! [image attached]"
```

Uses `AgentTool` (not `sub_agents`) so `image_agent` stays in control of the full orchestration loop.

---

### 2. Prompt Agent (`prompt_agent`)

Writes a polished Flux Schnell prompt without generating the image. Returns it formatted for copying.

> User: *"write me a prompt for a neon cyberpunk alley"*
> Agent: *"📝 Your Flux Schnell Prompt: [detailed prompt]"*

---

### 3. Newsletter Agent (`newsletter_agent`)

Multi-phase conversational flow — finds news, confirms with the user, writes the newsletter, allows up to 5 edit rounds.

```mermaid
sequenceDiagram
    participant U as User
    participant NA as newsletter_agent
    participant CS as Claude Web Search
    participant D as output/

    U->>NA: "create a newsletter"
    NA->>CS: search_web("most sensational AI tech news this week")
    CS-->>NA: articles + URLs
    NA->>U: 📰 4-story shortlist — "Do these look good?"
    U->>NA: "yes"
    NA->>CS: fetch_article(url) × 4
    CS-->>NA: full article text
    NA->>U: full newsletter draft — "Edit 0/5 — reply to change or say save"
    U->>NA: "change the intro"
    NA->>U: updated draft — "Edit 1/5"
    U->>NA: "save it"
    NA->>D: save_newsletter_draft("issue_2026_03_20.md")
    NA->>U: "✅ Newsletter saved!"
```

**Newsletter format (exact Tech Blueprint structure):**
- Welcome block with 4 story headlines
- 🌎 Transformational News → What / Why / How
- ☄️ Educational News → What / Why / How
- 💥 Creativity Corner → What / Why / How
- 🤖 Hi-Tech News → What / Why / How
- 🔮 Magical Productivity Hack (named framework + 5 action steps)

---

### 4. Tech Finder Agent (`tech_finder_agent`)

Fast news search — returns the top 5 latest articles on any tech topic.

```
🔍 Top 5 results for: humanoid robots

1️⃣ *Figure 02 Ships to BMW Factory*  📅 2026-03-19
https://...

2️⃣ *Tesla Optimus Hits 1,000 Units*  📅 2026-03-18
https://...
```

---

### 5. Content Saver Agent (`content_saver_agent`)

Saves URLs and images to the user's Notion workspace with smart categorisation.

```mermaid
sequenceDiagram
    participant U as User
    participant CSA as content_saver_agent
    participant C as Claude Vision
    participant N as Notion API

    alt URL shared
        U->>CSA: "save this https://techcrunch.com/..."
        CSA->>CSA: extract_page_content(url)
        CSA->>N: save_to_notion(title, category, summary, tags, url)
    else Image shared via WhatsApp
        U->>CSA: [image attachment] "save this"
        CSA->>C: analyze_image_content(twilio_media_url)
        C-->>CSA: {title, category, summary, tags}
        CSA->>N: save_to_notion(...)
    end

    N-->>CSA: notion_page_url
    CSA->>U: "✅ Saved to Notion! 📌 [title] 📂 [category]"
```

---

## Session Management

Sessions are keyed by the user's identity — phone number for WhatsApp, `X-Session-ID` header for the mobile app:

| Client | Session key | Where set |
|---|---|---|
| WhatsApp | `From` field (e.g. `whatsapp:+44...`) | Twilio form data |
| Mobile app | `X-Session-ID` header | App generates UUID on first launch, stores in `expo-secure-store` |

`InMemorySessionService` stores full conversation history per user. Sessions reset on server restart.

---

## A2A Protocol Flow (Mobile App)

```mermaid
sequenceDiagram
    participant App as 📱 Expo App
    participant S as Railway Server

    App->>S: GET /.well-known/agent.json
    S-->>App: Agent Card (name, description, 5 skills, /a2a URL)
    App->>App: Store "Ananya's Agent Hub", show in Discover tab

    App->>S: POST /a2a {method: "message/stream", message: "...", X-Session-ID: uuid}
    S-->>App: SSE: {state: "submitted"}
    S-->>App: SSE: {state: "working"}
    Note over S: ADK router runs, sub-agent responds
    S-->>App: SSE: {state: "completed", message: {parts: [{text: "..."}]}}
    App->>App: Display agent reply in chat bubble
```

---

## Full Data Flow — WhatsApp (Sequence)

```mermaid
sequenceDiagram
    participant U as 📱 User (WhatsApp)
    participant T as Twilio
    participant W as /webhook
    participant BG as BackgroundTask
    participant R as Router Agent
    participant SA as Sub-Agent

    U->>T: "find news on AI chips"
    T->>W: POST /webhook (Body, From, NumMedia...)
    W-->>T: 200 <Response/> (instant — beats 15s timeout)
    W->>BG: add_task(_handle, message, from_number)
    BG->>BG: set _current_recipient (for send_status_update)
    BG->>R: _run_agent(message, user_id=from_number)
    R->>SA: transfer_to_agent("tech_finder_agent")
    SA->>SA: search_news("AI chips")
    SA-->>R: formatted top 5 results
    R-->>BG: final_response text
    BG->>T: REST API: messages.create(to=from_number, body=response)
    T->>U: "🔍 Top 5 results for: AI chips..."
```

---

## All Tools Reference

| Tool | Used by | External API | Returns |
|---|---|---|---|
| `generate_image` | `image_generator` | fal.ai Flux Schnell (async queue) | `{image_url, saved_path, filename}` |
| `search_news` | `tech_finder_agent` | Claude native web search | `{message: WhatsApp-formatted string}` |
| `search_web` | `newsletter_agent` | Claude native web search | `{content: titles, URLs, summaries}` |
| `fetch_article` | `newsletter_agent` | httpx GET + HTML strip | `{content: plain text ≤4000 chars}` |
| `save_newsletter_draft` | `newsletter_agent` | — local file | `{path, bytes_written}` |
| `extract_page_content` | `content_saver_agent` | httpx GET + HTML strip | `{title, content, domain, url}` |
| `analyze_image_content` | `content_saver_agent` | Claude Vision (base64) | `{title, category, summary, tags}` |
| `save_to_notion` | `content_saver_agent` | Notion REST API | `{notion_url, title, category}` |
| `send_status_update` | all agents | Twilio REST API | Sends progress message to WhatsApp |

---

## Building Blocks Summary

| Component | Type | Role |
|---|---|---|
| `router_agent` | `LlmAgent` + `sub_agents` | Classifies intent, transfers to specialist |
| `image_agent` | `LlmAgent` + `AgentTool` | Multi-turn prompt → approve → generate loop |
| `prompt_specialist` | `LlmAgent`, no tools | Writes detailed Flux Schnell prompts |
| `image_generator` | `LlmAgent` + `generate_image` | Calls fal.ai, returns image URL |
| `prompt_agent` | `LlmAgent`, no tools | Standalone prompt writing |
| `newsletter_agent` | `LlmAgent` + 4 tools | Multi-phase: discover → confirm → write → edit → save |
| `tech_finder_agent` | `LlmAgent` + `search_news` | Top 5 latest news links |
| `content_saver_agent` | `LlmAgent` + 4 tools | URL/image → Notion with AI categorisation |
| `InMemorySessionService` | ADK | Per-user conversation history |
| `Runner` | ADK | Drives the agentic loop |
| `FastAPI BackgroundTasks` | FastAPI | Runs agent after instant 200 response |
| `POST /webhook` | FastAPI route | Twilio WhatsApp interface |
| `POST /a2a` | FastAPI route | A2A mobile app interface (SSE streaming) |
| `GET /.well-known/agent.json` | FastAPI route | A2A Agent Card discovery |

---

## Why `sub_agents` for routing vs `AgentTool` for image workflow?

| Mechanism | Where used | Why |
|---|---|---|
| `sub_agents` + `transfer_to_agent` | Router → all specialists | Transfer preserves conversation continuity across multiple user messages |
| `AgentTool` | `image_agent` → `prompt_specialist` / `image_generator` | Parent gets the result back and orchestrates the next step |

The image workflow requires the parent to orchestrate: call prompt_specialist → show result → wait for user approval → call image_generator. `AgentTool` returns the result to the parent so it can drive this loop. `transfer_to_agent` would hand off control permanently, breaking the workflow.

---

## Configuration

**`.env`** (repo root):
```
ANTHROPIC_API_KEY=...        # Claude Sonnet 4.6 via LiteLLM + Claude web search + Vision
FAL_KEY=...                  # fal.ai image generation
TWILIO_ACCOUNT_SID=...
TWILIO_AUTH_TOKEN=...
TWILIO_WHATSAPP_FROM=whatsapp:+14155238886
NOTION_API_KEY=...           # content_saver_agent
NOTION_DATABASE_ID=...       # content_saver_agent
```

**Install:**
```bash
pip install -e ".[hub]"
```

**Run locally:**
```bash
uvicorn whatsapp_hub.agent_whatsapp_hub.agent_whatsapp_hub:app --reload --port 8000
ngrok http 8000
# Twilio sandbox → https://<ngrok-id>.ngrok-free.app/webhook (POST)
# Mobile app  → http://localhost:8000
```

**Deploy (Railway):**
```bash
git push  # railway.toml handles build + start command
```

Generated images and newsletter drafts are saved to `whatsapp_hub/agent_whatsapp_hub/output/`.

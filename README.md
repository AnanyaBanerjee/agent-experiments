# agent-experiments

A collection of experimental AI agents built while exploring different frameworks, models, and interfaces. These agents were the foundation for the production hubs in [my-agent](https://github.com/AnanyaBanerjee/my-agent).

---

## What's in here

| Folder | Description |
|---|---|
| `image_generation_agent/` | Image generation agents built with raw Anthropic API, Google ADK + LiteLLM (Claude, Gemini, GPT-4o), and a Twilio WhatsApp interface |
| `tech_finder_agent/` | Standalone agent that searches for tech news and delivers it via WhatsApp |
| `tech_newsletter_agent/` | CLI agent that researches and drafts a weekly tech newsletter |
| `whatsapp_hub/` | Legacy monolithic hub routing WhatsApp messages to all agents via Twilio |

---

## Agents

### image_generation_agent

| Agent | Model | Interface |
|---|---|---|
| `agent_guide` | Claude (Anthropic API direct) | CLI |
| `agent_adk` | Claude (Google ADK + LiteLLM) | CLI |
| `agent_adk_gemini` | Gemini (Google ADK) | CLI |
| `agent_adk_openai` | GPT-4o (Google ADK + LiteLLM) | CLI |
| `whatsapp_twilio` | GPT-4o via agent_adk_openai | WhatsApp (Twilio sandbox) |

### tech_finder_agent
Searches the web for the latest tech news and sends results via WhatsApp using Twilio.

### tech_newsletter_agent
Multi-step research agent that finds stories, fetches articles, and writes a formatted Tech Blueprint newsletter draft saved as a `.md` file.

### whatsapp_hub
The original unified router — a single FastAPI server that received WhatsApp messages via Twilio and routed them to image generation, newsletter, tech news, and Notion-saving agents. Replaced by the focused hubs in [my-agent](https://github.com/AnanyaBanerjee/my-agent).

---

## Setup

```bash
# Install all dependencies
pip install -e ".[all]"

# Or install for a specific agent
pip install -e ".[anthropic]"   # agent_guide
pip install -e ".[adk,litellm]" # agent_adk or agent_adk_openai
pip install -e ".[adk]"         # agent_adk_gemini
```

Requires a `.env` file at the repo root:
```
ANTHROPIC_API_KEY=sk-ant-...
FAL_KEY=...                     # for image generation (fal.ai)
TWILIO_ACCOUNT_SID=...          # for WhatsApp agents
TWILIO_AUTH_TOKEN=...
```

---

## Relationship to my-agent

These agents were refactored into focused, production-ready hubs in the [my-agent](https://github.com/AnanyaBanerjee/my-agent) repo, which uses the A2A protocol instead of Twilio and deploys each hub as a separate Railway service.

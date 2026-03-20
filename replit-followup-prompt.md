# Replit Follow-Up: Connect to Real Backend

The app is built. Now customise it to connect to my real backend.
Make all of these changes:

---

## 1. Connect to My Real Server

Remove the mock/demo agent. Replace it with my real server:

| | |
|---|---|
| **Base URL** | `https://my-agent-production-deb5.up.railway.app` |
| **Agent Card** | `https://my-agent-production-deb5.up.railway.app/.well-known/agent.json` |
| **A2A endpoint** | `https://my-agent-production-deb5.up.railway.app/a2a` |

On first app launch, automatically fetch the Agent Card from `/.well-known/agent.json`
and pre-load it as the default agent. The user should open the app and see
**"The Tech Blueprint Hub"** ready to chat — no manual URL entry needed.

---

## 2. Add `X-Session-ID` Header to Every Request

This is the most critical change. On first app launch:

1. Generate a UUID v4
2. Store it permanently in `expo-secure-store` under the key `"session_id"`
3. Load it on every app start

Include this header on **every** request to `/a2a`:

```
X-Session-ID: <the stored UUID>
```

Without this, the server loses conversation context between messages and
multi-turn flows will break completely.

---

## 3. Use `message/stream` for All Messages

Always use method `"message/stream"` (not `"message/send"`).

The server streams SSE events in this order:

| Event | UI action |
|---|---|
| `submitted` | Show typing indicator |
| `working` | Keep showing typing indicator |
| `completed` | Display agent reply, hide typing indicator |

The completed event contains the full response text at:

```
result.status.message.parts[0].text
```

---

## 4. Handle Long Messages

Newsletter drafts can be **1500–3000 characters**. Make sure:

- Chat bubbles are **not truncated** — show the full text
- Long agent messages are scrollable within the chat
- Do **not** cut off or add a "read more" — display everything

---

## 5. No Auth Required

The server does not require a bearer token. Remove any auth token prompts
or input fields. Only the `X-Session-ID` header is needed.

---

## 6. Show Skills on Agent Profile Screen

The Agent Card from `/.well-known/agent.json` contains 5 skills.
Show them on the Agent Profile screen with their example prompts so the
user knows what they can ask.

| Skill | Example prompt |
|---|---|
| 🖼️ Image Generation | _"Generate an image of a futuristic city at sunset"_ |
| ✍️ Prompt Writing | _"Write me a prompt for a neon cyberpunk street scene"_ |
| 📰 Tech Newsletter | _"Create a newsletter"_ / _"Draft this week's tech newsletter"_ |
| 🔍 Tech News Finder | _"Find latest news on OpenAI"_ |
| 💾 Save to Notion | _"Save this https://..."_ |

---

## 7. Understand the Multi-Turn Flows

The agent runs **conversational flows that span multiple messages**.
The user replies back and forth in the same chat thread. This works
automatically as long as `X-Session-ID` is sent consistently.

**Image flow (2–3 turns):**
```
User:  "generate an image of a cyberpunk city"
Agent: shows a prompt draft, asks for approval
User:  "make it more neon and rainy"
Agent: shows refined prompt, asks again
User:  "yes generate it"
Agent: returns the image URL
```

**Newsletter flow (up to 7–8 turns):**
```
User:  "create a newsletter"
Agent: presents 4 story options, asks to confirm
User:  "yes looks good"
Agent: writes and sends the full newsletter draft, asks for edits
User:  "change the intro paragraph"
Agent: sends updated draft
User:  "save it"
Agent: confirms saved
```

---

## 8. Verify These Flows Work End to End

After making changes, test these in the app:

**Single turn:**
- Send `"find latest news on AI"` → agent replies with 5 links

**Multi-turn (image):**
- Send `"generate an image of a sunset"`
- Agent shows a prompt and asks for approval
- Reply `"yes generate it"`
- Agent generates and returns the image

**Multi-turn (newsletter):**
- Send `"create a newsletter"`
- Agent shows 4 story options
- Reply `"yes looks good"`
- Agent sends the full newsletter draft
- Reply `"save it"`
- Agent confirms saved

> **If multi-turn breaks** (agent forgets context between messages),
> the `X-Session-ID` header is not being sent correctly — fix that first.

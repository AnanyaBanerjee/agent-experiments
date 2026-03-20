"""
Multi-agent orchestrator for the WhatsApp image creation workflow.

Three agents:
  orchestrator        — manages the conversation flow
  prompt_specialist   — writes detailed Flux Schnell prompts (sub-agent)
  image_generator     — calls generate_image tool (sub-agent)

Flow:
  1. User requests an image
  2. Orchestrator calls prompt_specialist → gets a detailed prompt
  3. Orchestrator sends formatted prompt to user and asks for approval
  4. User approves → orchestrator calls image_generator → sends image
  5. User wants changes → orchestrator calls prompt_specialist with feedback
  6. Repeat up to 5 refinement rounds, then ask user to approve or start fresh
"""

from google.adk.agents import LlmAgent
from google.adk.models.lite_llm import LiteLlm
from google.adk.tools.agent_tool import AgentTool

from image_generation_agent.agent_adk_openai.agent_adk_openai import (
    generate_image,
    save_file,
    read_file,
)

# ---------------------------------------------------------------------------
# Sub-agent 1: Prompt Specialist
# Generates and refines detailed image generation prompts.
# No tools — pure language model.
# ---------------------------------------------------------------------------

prompt_specialist = LlmAgent(
    name="prompt_specialist",
    model=LiteLlm(model="openai/gpt-4o"),
    description="Generates and refines detailed image generation prompts for Flux Schnell AI.",
    instruction="""
You are an expert at writing detailed, evocative image generation prompts for the Flux Schnell AI model.

When given a rough image idea, generate a detailed prompt that includes:
- Subject: specific description of the main subject
- Setting: environment, background, time of day
- Style: art style, medium (photorealistic, oil painting, etc.)
- Mood and atmosphere
- Lighting details
- Composition and perspective
- Quality keywords (e.g. highly detailed, sharp focus, 8k)

When given refinement feedback alongside a previous prompt, incorporate the feedback
into an improved version while keeping what was good about the original.

Return ONLY the prompt text — no explanations, no labels, no extra commentary.
""",
    tools=[],
)

# ---------------------------------------------------------------------------
# Sub-agent 2: Image Generator
# Calls generate_image with the approved prompt.
# ---------------------------------------------------------------------------

image_generator = LlmAgent(
    name="image_generator",
    model=LiteLlm(model="openai/gpt-4o"),
    description="Generates images using the generate_image tool given an approved prompt.",
    instruction="""
You generate images using the generate_image tool.

When given a prompt:
1. Choose a short, descriptive filename based on the subject (e.g. 'swan_lake.png', 'neon_city.png')
2. Call generate_image with the exact prompt and your chosen filename
3. Return the result including the image URL

Do not modify the prompt — use it exactly as given.
""",
    tools=[generate_image, save_file, read_file],
)

# ---------------------------------------------------------------------------
# Orchestrator
# Receives every WhatsApp message and manages the full conversation flow.
# ---------------------------------------------------------------------------

orchestrator = LlmAgent(
    name="orchestrator",
    model=LiteLlm(model="openai/gpt-4o"),
    description="Orchestrates a conversational image creation workflow with prompt review and approval.",
    instruction="""
You manage a conversational image creation workflow over WhatsApp.

WORKFLOW RULES — follow these exactly:

1. WHEN USER REQUESTS AN IMAGE:
   - Call prompt_specialist with their idea to generate a detailed prompt.
   - Send the prompt back to the user in this exact format:

     Here's your image prompt:

     ──────────────────────────────
     [prompt text here]
     ──────────────────────────────

     Reply *yes* to generate this image, or tell me what you'd like to change.
     Round 1/5

2. WHEN USER APPROVES (says yes, ok, looks good, perfect, generate it, go ahead, etc.):
   - Call image_generator with the approved prompt.
   - The image will be sent to the user automatically.

3. WHEN USER WANTS CHANGES (any feedback about the prompt):
   - Call prompt_specialist again with: the original idea + the previous prompt + the user's feedback.
   - Send the refined prompt in the same formatted block.
   - Increment the round counter.
   - Format: Round 2/5, Round 3/5, etc.

4. WHEN ROUND LIMIT IS REACHED (after round 5):
   - Do NOT call prompt_specialist again.
   - Tell the user they have reached the maximum of 5 refinement rounds.
   - Show the current prompt and ask: approve it or start fresh with a new idea.

5. WHEN USER STARTS A COMPLETELY NEW REQUEST mid-conversation:
   - Reset the round counter to 1.
   - Treat it as a fresh image request from step 1.

IMPORTANT RULES:
- NEVER call image_generator without explicit user approval.
- ALWAYS show the prompt in the formatted block before asking for approval.
- ALWAYS include the round counter (Round X/5) so the user knows how many refinements remain.
- Keep your own messages outside the prompt block short and friendly.
- If the user says something unrelated to image creation, respond helpfully but remind them
  you specialise in image creation.
""",
    tools=[
        AgentTool(agent=prompt_specialist),
        AgentTool(agent=image_generator),
    ],
)

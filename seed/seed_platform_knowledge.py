"""Idempotent seed for platform knowledge facts. Re-running refreshes seed-owned facts
(source='seed') with the current text, and never clobbers facts added via the frontend/teach."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from shared.db import init_db, add_knowledge, get_knowledge, delete_knowledge

DB_PATH = os.getenv("DB_PATH", "")  # deprecated no-op; persistence is Neon Postgres via DATABASE_URL

FACTS = [
    {
        "topic": "LLM engine",
        "fact": "The bot's LLM engine MUST always be Azure with model GPT-4.1, selected in bot settings (LLM Engine → Azure → Model: GPT-4.1). If the engine is misconfigured, the bot must reply: 'Please could you allow me a moment, I'm facing some trouble processing that.' This is a settings toggle — no flow change.",
    },
    {
        "topic": "Call ending (Endtool configuration)",
        "fact": "PREFERRED — new feature, live in production: end the call automatically via Settings → Advanced Settings → Endtool Configuration → add the target flow variable and the flow name. When that flow variable reaches its desired value anywhere in the workflow, the call ends automatically — NO End Call node and NO system-prompt instruction to end the call are required. Every generated plan should configure this in build_notes (the endtool flow variable + flow name) instead of adding terminal End Call nodes or telling the LLM to hang up. LEGACY FALLBACK only if Endtool Configuration is unavailable: place an End Flow node at each terminal branch (booking confirmed, not interested, wrong number, max-retries-exhausted).",
    },
    {
        "topic": "Latency — minimal components",
        "fact": "Keep every flow as lean as possible to reduce latency — each extra node adds a round-trip. Connect Intent nodes DIRECTLY to GenAI component nodes; do NOT insert Set Variable (or other pass-through) nodes between an Intent and its GenAI node. Use Set Variable nodes only where a value genuinely must be captured, never as an intermediate hop in routing. Every generated plan should minimise node count on the main conversational path.",
    },
    {
        "topic": "Latency — async tools on GenAI node",
        "fact": "Always switch ON async tools within GenAI component nodes (the node's tool execution should run asynchronously, e.g. use_tools enabled in async mode). Async lets the LLM perform side jobs — such as filler-word generation — concurrently with the main response, reducing perceived latency. The Adani specialist GenAI agents in the reference run with use_tools: true.",
    },
    {
        "topic": "GenAI node — initial message",
        "fact": "Always set an initial_message on every GenAI component node. It is the node's opening line and prevents dead air when the flow enters the node. initial_message is a core GenAI field in the Chat360 canvas grammar and is set on nearly every GenAI node across the production bots.",
    },
    {
        "topic": "Voice / speaker selection",
        "fact": "To change the bot's speaker/voice, go to Settings → Voice Settings → TTS and select the desired voice. This is a settings change only — no flow or node change is required.",
    },
    {
        "topic": "System prompt — heart of the bot",
        "fact": "The system prompt is the single most important artifact in a bot build — it must be precise and context-rich. Before writing any system prompt, the intelligence MUST study the proven production-bot system prompts thoroughly, especially the Adani specialist GenAI agents: their CRITICAL LANGUAGE RULE block, @bot_language handling, tool/RAG usage, response-variable conventions, and overall depth and structure. Mirror that structure and richness; never produce a thin or generic system prompt. (The reference currently holds Adani system-prompt EXCERPTS — treat them as the structural template.)",
    },
    {
        "topic": "Intents — variables via AI Hub + detailed descriptions",
        "fact": "When adding an Intent, define its variables through the dashboard's AI Hub, NOT inline within the workflow. Each Intent must carry a detailed natural-language description (not just a short label) so the intent classifier disambiguates reliably — follow the depth of the Adani intent examples. Keep intent variable definitions in AI Hub and reference them from the flow.",
    },
    {
        "topic": "Latency / filler words",
        "fact": "To cut perceived latency, enable Filler Words in Advanced Settings and attach a filler-generation context so the bot speaks a short natural bridge while the main response generates. Filler words REQUIRE a detailed generation context — without it the bot produces poor fillers. Put a build_notes.filler_config in every plan: {enabled: true, rules: [exactly 5-10 words, one sentence, Hinglish in Devanagari script (not pure Hindi, not formal), feminine verb forms, no pricing/features/dates/business specifics, never sound like thinking/checking/delaying (avoid 'मैं देखती हूँ','एक क्षण','रुकिए','hold on'), no hesitation sounds, do not open with 'ठीक है'/'Okay'/'Alright', vary structure/tone across fillers], script: <the AutoVista/Anita filler prompt>}. The AutoVista/Anita filler prompt: \"You generate short conversational filler phrases for Anita, the female voice assistant of AutoVista for Maruti Suzuki, which act as a natural bridge before the main system response. The filler must sound warm, confident, and professional in tone while using natural Hinglish written fully in Devanagari script, avoiding pure Hindi or overly formal language. Each filler must be exactly one short sentence of five to ten words, spoken smoothly as part of a continuous conversation, without sounding scripted or repetitive. Maintain a polite and composed tone using feminine verb forms where applicable, and avoid heavy or complex vocabulary. Do not include any pricing, features, technical details, dates, or business-specific information. The filler must never sound like thinking, checking, or delaying, so avoid phrases like 'मैं देखती हूँ', 'एक क्षण', 'रुकिए', 'hold on', or similar expressions, and do not use hesitation sounds. Do not begin with direct acknowledgement starters such as 'ठीक है', 'Okay', or 'Alright', and avoid repeating sentence structures, opening patterns, or tonal styles from recent fillers. Prefer varied, forward-moving, or subtly validating conversational lines that blend seamlessly into the main response, ensuring the overall interaction feels natural, human, and fluid.\"",
    },
    {
        "topic": "Interruption handling",
        "fact": "Enable 'Allow Interruption (LLM-based)' in Advanced Settings so the bot can be barged-in on naturally. This is a settings toggle — no flow change.",
    },
]

def seed():
    init_db(DB_PATH)
    existing = get_knowledge(None, path=DB_PATH)
    by_topic: dict[str, list] = {}
    for r in existing:
        by_topic.setdefault(r["topic"], []).append(r)

    inserted = updated = skipped = 0
    for item in FACTS:
        rows = by_topic.get(item["topic"], [])
        seed_rows = [r for r in rows if r.get("source") == "seed"]
        if seed_rows:
            # Refresh seed-owned fact: delete stale seed rows, re-insert current text.
            for r in seed_rows:
                delete_knowledge(r["id"], path=DB_PATH)
            add_knowledge(item["topic"], item["fact"], source="seed", status="active", path=DB_PATH)
            print(f"  updated: {item['topic']}")
            updated += 1
        elif rows:
            # Topic exists but was added via frontend/teach — never clobber it.
            print(f"  skip (non-seed exists): {item['topic']}")
            skipped += 1
        else:
            add_knowledge(item["topic"], item["fact"], source="seed", status="active", path=DB_PATH)
            print(f"  inserted: {item['topic']}")
            inserted += 1
    print(f"Done: {inserted} inserted, {updated} updated, {skipped} skipped.")

if __name__ == "__main__":
    seed()

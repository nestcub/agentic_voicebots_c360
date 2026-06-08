"""Idempotent seed for platform knowledge facts. Safe to run multiple times."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from shared.db import init_db, add_knowledge, get_knowledge

DB_PATH = os.getenv("DB_PATH", "intelligence_fabric.db")

FACTS = [
    {
        "topic": "LLM engine",
        "fact": "The bot's LLM engine MUST always be Azure with model GPT-4.1, selected in bot settings (LLM Engine → Azure → Model: GPT-4.1). If the engine is misconfigured, the bot must reply: 'Please could you allow me a moment, I'm facing some trouble processing that.' This is a settings toggle — no flow change.",
    },
    {
        "topic": "Call disconnection",
        "fact": "To make the voice bot hang up, add an End Flow component (PREFERRED) at every terminal branch — booking confirmed, not interested, wrong number, and max-retries-exhausted — and route each terminal stage into it. Optionally also instruct termination in the system prompt, but the End Flow node is what actually disconnects. Every generated plan must include End Flow terminal nodes in workflow_blueprint and a build_notes.canvas_instructions step to wire them.",
    },
    {
        "topic": "Latency / filler words",
        "fact": "To cut perceived latency, enable Filler Words in Advanced Settings and attach a filler-generation context so the bot speaks a short natural bridge while the main response generates. Put a build_notes.filler_config in every plan: {enabled: true, rules: [exactly 5-10 words, one sentence, Hinglish in Devanagari script (not pure Hindi, not formal), feminine verb forms, no pricing/features/dates/business specifics, never sound like thinking/checking/delaying (avoid 'मैं देखती हूँ','एक क्षण','रुकिए','hold on'), no hesitation sounds, do not open with 'ठीक है'/'Okay'/'Alright', vary structure/tone across fillers], script: <the AutoVista/Anita filler prompt>}. The AutoVista/Anita filler prompt: \"You generate short conversational filler phrases for Anita, the female voice assistant of AutoVista for Maruti Suzuki, which act as a natural bridge before the main system response. The filler must sound warm, confident, and professional in tone while using natural Hinglish written fully in Devanagari script, avoiding pure Hindi or overly formal language. Each filler must be exactly one short sentence of five to ten words, spoken smoothly as part of a continuous conversation, without sounding scripted or repetitive. Maintain a polite and composed tone using feminine verb forms where applicable, and avoid heavy or complex vocabulary. Do not include any pricing, features, technical details, dates, or business-specific information. The filler must never sound like thinking, checking, or delaying, so avoid phrases like 'मैं देखती हूँ', 'एक क्षण', 'रुकिए', 'hold on', or similar expressions, and do not use hesitation sounds. Do not begin with direct acknowledgement starters such as 'ठीक है', 'Okay', or 'Alright', and avoid repeating sentence structures, opening patterns, or tonal styles from recent fillers. Prefer varied, forward-moving, or subtly validating conversational lines that blend seamlessly into the main response, ensuring the overall interaction feels natural, human, and fluid.\"",
    },
    {
        "topic": "Interruption handling",
        "fact": "Enable 'Allow Interruption (LLM-based)' in Advanced Settings so the bot can be barged-in on naturally. This is a settings toggle — no flow change.",
    },
]

def seed():
    init_db(DB_PATH)
    existing_topics = {r["topic"] for r in get_knowledge(None, path=DB_PATH)}
    inserted, skipped = 0, 0
    for item in FACTS:
        if item["topic"] in existing_topics:
            print(f"  skip (exists): {item['topic']}")
            skipped += 1
        else:
            add_knowledge(item["topic"], item["fact"], source="seed", status="active", path=DB_PATH)
            print(f"  inserted: {item['topic']}")
            inserted += 1
    print(f"Done: {inserted} inserted, {skipped} skipped.")

if __name__ == "__main__":
    seed()

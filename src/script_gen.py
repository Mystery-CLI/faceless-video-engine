"""Daily topic selection + script/metadata generation, with repeat avoidance."""
import json
import re
from datetime import date
from pathlib import Path

from . import llm

HISTORY_FILE = Path(__file__).resolve().parent.parent / "data" / "topics_history.json"

CTA_SENTENCE = "Like and subscribe for more mind facts."


def enforce_cta(script: str) -> str:
    """Guarantee the script ends with the exact CTA, replacing any drifted variant."""
    sentences = re.split(r"(?<=[.!?])\s+", script.strip())
    while sentences and re.search(r"\b(subscribe|like and)\b", sentences[-1], re.IGNORECASE):
        sentences.pop()
    sentences.append(CTA_SENTENCE)
    return " ".join(sentences)

PROMPT_TEMPLATE = """You are the head writer for a viral faceless YouTube Shorts channel.

Niche: {niche}
Persona: {persona}
Today's date: {today}

Topics already covered (NEVER repeat or closely paraphrase these):
{history}

Live audience data from this channel's past uploads (real viewers voting with
their attention):
{performance}
Steer new candidates toward the emotional angle and sub-theme flavor of the
overperformers and away from the underperformers — but NEVER repeat or
paraphrase a covered topic.

Task: silently brainstorm 5 fresh topic candidates in this niche — each from a DIFFERENT
sub-theme of the niche, avoiding the sub-themes of the most recent topics above so
consecutive videos feel varied while staying on-niche.

CRITICAL topic selection rule — obscurity is the product:
- Every candidate must be something most viewers have NEVER heard of, have forgotten,
  or actively ignore. The target reaction is "wait, WHAT? why did nobody tell me this?"
- BANNED: anything a casual viewer already knows from school, TikTok, or common
  self-help content (e.g. Dunning-Kruger, Pavlov's dogs, placebo effect, left/right
  brain, 10% of the brain, Maslow's pyramid, fight-or-flight basics). If normal people
  could name it, it is too famous — discard it.
- A famous topic is allowed ONLY if the entire video is a little-known twist that even
  fans of the niche don't know (a buried detail, a modern finding that flips it, a
  real-world consequence nobody connects to it).
- Prefer: obscure named effects, weird well-replicated findings, forgotten experiments,
  everyday behaviors with hidden causes, things people do daily without knowing why.

CRITICAL relevance rule — obscure is NOT enough, it must hit the viewer where they live:
- Every candidate must have direct personal stakes: their relationships, attraction,
  money, career, social status, self-image, or how other people secretly judge and
  treat them. The viewer should feel exposed, seen, or slightly alarmed — "this is
  about ME" — and immediately crave the next video.
- BANNED: neutral perceptual/sensory trivia and brain-quirk curiosities with no
  emotional consequence (e.g. time-perception oddities, visual illusions, why clocks
  seem to freeze). "Huh, neat" is failure. If knowing the fact changes nothing about
  how the viewer sees their own life, discard it.
- Strongest angles: why people secretly like or dislike you, hidden signals you give
  off without knowing, invisible forces steering your money and decisions, persuasion
  and manipulation tactics quietly used on you every day, what your habits reveal
  about you.

Score each candidate 1-10 on: personal stakes (does it hit the viewer's relationships,
money, status, or self-image?), craving factor (do they NEED more after watching?),
obscurity (would a casual viewer already know this? low score if yes),
scroll-stopping power, and comment bait. Then write the video ONLY for the single
highest-scoring topic. Only produce a
video you are confident can attract views, likes, and new subscribers — if a candidate
feels generic or familiar, discard it.

Rules for the script:
- Total length {target_words} words (~{target_seconds} seconds spoken).
- Sentence 1 is the HOOK and must be a direct question to the viewer OR a shocking
  claim, under 12 words, creating an instant curiosity gap. NEVER open with context,
  background, or a topic announcement. Bad: "Psychology has many interesting effects."
  Good: "Your brain is lying to you right now." / "Why do you buy things you hate?"
- Short punchy sentences. No filler, no "welcome back", no self-reference.
- Build the script around the unknown angle: open the curiosity gap, reveal the
  little-known fact as the payoff, then land ONE concrete "this is happening in your
  life right now" example so the viewer feels it personally.
- Must be factually accurate and non-harmful. No medical/financial advice. Never
  invent or exaggerate a finding to make it more shocking — obscure but TRUE.
- Advertiser-friendly language only: no profanity, violence, sexual content, or
  shock-for-shock's-sake claims — the video must stay fully monetizable.
- Second-to-last beat: a twist, cliffhanger, or question that provokes comments.
- The FINAL sentence must be EXACTLY: "Like and subscribe for more mind facts."
  Do not shorten it, reword it, or drop the word "like".
- Plain spoken text only: no emojis, no stage directions, no headers.

Return ONLY valid JSON, no markdown, exactly this shape:
{{
  "topic": "short internal label for the topic",
  "title": "YouTube title under 90 chars, curiosity-driven, ends with #Shorts",
  "description": "2-3 sentence description with a hook, an invitation to like & subscribe, and 3-5 hashtags on the last line",
  "tags": ["8-12", "seo", "tags"],
  "script": "the full spoken script as one string",
  "music_mood": "exactly one of: suspense, chill — suspense for mysterious/surprising topics, chill for warm/reflective ones",
  "comment": "a short question (under 20 words) to post as the channel's own comment under the video, written to provoke replies and personal stories",
  "playlist": "exactly one of: {playlists}",
  "search_terms": ["5 stock-video search phrases (2-3 words each), IN CHRONOLOGICAL ORDER matching the script's narrative from hook to ending. Each must be a concrete filmable subject that exists in stock libraries (people, objects, places, actions) — never abstract concepts. e.g. 'woman thinking closeup', 'crowded subway station'"]
}}"""


def load_history() -> list:
    if HISTORY_FILE.exists():
        return json.loads(HISTORY_FILE.read_text(encoding="utf-8-sig"))
    return []


def save_history_entry(entry: dict) -> None:
    history = load_history()
    history.append(entry)
    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    HISTORY_FILE.write_text(json.dumps(history, indent=2), encoding="utf-8")


def generate_video_plan(config: dict, forced_topic: str | None = None) -> dict:
    history = load_history()
    recent = [h["topic"] for h in history[-60:]]
    target_seconds = config["video"]["target_seconds"]
    try:
        from . import analytics
        performance = analytics.performance_block()
    except Exception as exc:  # the feedback signal must never break the daily run
        print(f"    performance signal skipped: {exc}")
        performance = "(no performance data yet — pick purely on the scoring rules)"
    prompt = PROMPT_TEMPLATE.format(
        performance=performance,
        niche=config["niche"],
        persona=config["channel_persona"],
        today=date.today().isoformat(),
        history="\n".join(f"- {t}" for t in recent) if recent else "(none yet)",
        target_words=int(target_seconds * 2.6),
        target_seconds=target_seconds,
        playlists=", ".join(config.get("playlists", ["Mind Facts"])),
    )
    if forced_topic:
        prompt += f"\n\nOverride: the topic MUST be about: {forced_topic}"

    plan = llm.generate_json(prompt, config)
    for key in ("topic", "title", "description", "tags", "script", "search_terms"):
        if key not in plan:
            raise RuntimeError(f"LLM plan missing key: {key}")
    plan["script"] = enforce_cta(plan["script"])
    if "#shorts" not in plan["title"].lower():
        plan["title"] = plan["title"].rstrip() + " #Shorts"
    return plan

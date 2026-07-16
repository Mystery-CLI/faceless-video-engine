"""Weekly long-form countdown: theme selection + per-item scripts, with repeat avoidance."""
import json
from datetime import date
from pathlib import Path

from . import llm

HISTORY_FILE = Path(__file__).resolve().parent.parent / "data" / "longform_history.json"

PROMPT_TEMPLATE = """You are the head writer for a faceless YouTube channel making long-form
countdown videos (8-10 minutes).

Niche: {niche}
Persona: {persona}
Today's date: {today}

Countdown themes already covered (NEVER repeat or closely paraphrase these):
{history}

Live audience data from this channel's past uploads (real viewers voting with
their attention):
{performance}
Steer the theme and items toward the emotional angle of the overperformers and
away from the underperformers — but NEVER repeat a covered theme.

Task: silently brainstorm 4 candidate countdown themes, score each 1-10 on obscurity,
mind-blow factor, and click appeal, then create ONE countdown video for the single
highest-scoring theme: "{items_count} <things> ..." where every item is a little-known
psychology fact. If a candidate feels generic or familiar, discard it.

CRITICAL selection rule — obscurity is the product:
- Every item must be something most viewers have NEVER heard of, have forgotten, or
  actively ignore. Target reaction: "wait, WHAT? why did nobody tell me this?"
- BANNED: anything a casual viewer knows from school, TikTok, or common self-help
  content (Dunning-Kruger, Pavlov's dogs, placebo effect, left/right brain, 10% of
  the brain, Maslow's pyramid, fight-or-flight basics).
- Prefer: obscure named effects, weird well-replicated findings, forgotten
  experiments, everyday behaviors with hidden causes.

CRITICAL relevance rule — obscure is NOT enough, every item must hit the viewer
where they live:
- Direct personal stakes only: their relationships, attraction, money, career,
  social status, self-image, or how other people secretly judge and treat them.
  The viewer should feel exposed, seen, or slightly alarmed — "this is about ME".
- BANNED: neutral perceptual/sensory trivia and brain-quirk curiosities with no
  emotional consequence. "Huh, neat" is failure. If knowing the fact changes
  nothing about how the viewer sees their own life, replace the item.
- Strongest angles: why people secretly like or dislike you, hidden signals you
  give off without knowing, invisible forces steering your money and decisions,
  persuasion tactics quietly used on you every day, what your habits reveal.
- Order items so the strongest, most mind-blowing one is LAST (#1) and the second
  strongest is FIRST, so the video opens hot and ends unforgettable.

Rules for every item script:
- {item_words} words maximum. Structure: the FIRST sentence is a mini-hook and must be
  a direct question to the viewer OR a shocking claim, under 12 words, creating an
  instant curiosity gap — NEVER open an item with context or a topic announcement.
  Then the reveal, then ONE concrete "this is happening in your life right now"
  example, and END the item on a twist or a question that provokes comments.
- Short punchy sentences. No filler, no "welcome back", no self-reference, no spoken
  transitions like "next up" or "moving on" (numbering is shown on screen, not spoken).
- Factually accurate — obscure but TRUE, never invented or exaggerated. No
  medical/financial advice.
- Advertiser-friendly language only: fully monetizable.
- Plain spoken text only: no emojis, no stage directions, no item numbers in the text.

Intro script ({intro_words} words max): the FIRST sentence must be a direct question
or shocking claim under 12 words — never context. Then open a huge curiosity gap and
promise the countdown ("...and number one will change how you see your own mind").
Outro script ({outro_words} words max): one-line payoff, ask which item shocked them
most (comment bait), then the FINAL sentence must be EXACTLY:
"Like and subscribe for more mind facts." Do not shorten or reword it.

Return ONLY valid JSON, no markdown, exactly this shape:
{{
  "theme": "short internal label for the countdown theme",
  "title": "YouTube title under 90 chars, curiosity-driven, includes the number {items_count}",
  "description": "3-4 sentence description with a hook, an invitation to like & subscribe, and 4-6 hashtags on the last line",
  "tags": ["10-15", "seo", "tags"],
  "thumbnail_text": "3-5 punchy words for the thumbnail, ALL CAPS energy",
  "music_mood": "exactly one of: suspense, chill",
  "comment": "a short question (under 20 words) to post as the channel's own comment, asking which item shocked them most",
  "playlist": "exactly one of: {playlists}",
  "intro": {{"script": "...", "search_terms": ["3 stock-video search phrases (2-3 words each), concrete filmable subjects that exist in stock libraries (people, objects, places, actions), never abstract concepts"]}},
  "items": [
    {{"name": "short display name of the effect/fact", "script": "...", "search_terms": ["4 stock-video search phrases (2-3 words each), IN CHRONOLOGICAL ORDER matching this item's story from mini-hook to ending, concrete filmable subjects only"]}}
  ],
  "outro": {{"script": "...", "search_terms": ["2 stock-video phrases"]}}
}}
The items array must contain exactly {items_count} entries, ordered from #{items_count} down to #1."""


def load_history() -> list:
    if HISTORY_FILE.exists():
        return json.loads(HISTORY_FILE.read_text(encoding="utf-8-sig"))
    return []


def save_history_entry(entry: dict) -> None:
    history = load_history()
    history.append(entry)
    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    HISTORY_FILE.write_text(json.dumps(history, indent=2), encoding="utf-8")


def generate_longform_plan(config: dict) -> dict:
    lf = config.get("longform", {})
    items_count = int(lf.get("items_count", 8))
    recent = [h["theme"] for h in load_history()[-40:]]
    try:
        from . import analytics
        performance = analytics.performance_block()
        # promotion engine: this week's best Short seeds the countdown theme
        data = analytics.get_performance()
        if data and data.get("videos"):
            from datetime import date as _d
            best = max(
                data["videos"],
                key=lambda v: v.get("views", 0)
                / max((_d.today() - _d.fromisoformat(v["date"])).days, 1),
            )
            performance += (
                f"\n\nTHIS WEEK'S PROVEN WINNER: \"{best['topic']}\" "
                f"({best.get('views', 0)} views). The audience voted with their "
                "attention: the countdown theme MUST build on the same emotional "
                "angle that made it win, WITHOUT repeating that topic as an item."
            )
    except Exception as exc:  # the feedback signal must never break the weekly run
        print(f"    performance signal skipped: {exc}")
        performance = "(no performance data yet — pick purely on the scoring rules)"
    prompt = PROMPT_TEMPLATE.format(
        performance=performance,
        niche=config["niche"],
        persona=config["channel_persona"],
        today=date.today().isoformat(),
        history="\n".join(f"- {t}" for t in recent) if recent else "(none yet)",
        items_count=items_count,
        item_words=int(lf.get("item_words", 95)),
        intro_words=int(lf.get("intro_words", 45)),
        outro_words=int(lf.get("outro_words", 35)),
        playlists=", ".join(config.get("playlists", ["Mind Facts"])),
    )
    plan = llm.generate_json(prompt, config)
    for key in ("theme", "title", "description", "tags", "thumbnail_text",
                "intro", "items", "outro"):
        if key not in plan:
            raise RuntimeError(f"LLM long-form plan missing key: {key}")
    if len(plan["items"]) < 3:
        raise RuntimeError(f"LLM returned only {len(plan['items'])} items")
    # the exact CTA is enforced in code, same as the Shorts pipeline
    from .script_gen import enforce_cta
    plan["outro"]["script"] = enforce_cta(plan["outro"]["script"])
    return plan

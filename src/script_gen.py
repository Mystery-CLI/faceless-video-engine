"""Daily topic selection + script/metadata generation, with repeat avoidance."""
import json
import re
from datetime import date
from pathlib import Path

from . import llm

HISTORY_FILE = Path(__file__).resolve().parent.parent / "data" / "topics_history.json"

# The editorial rules the prompt enforces. These defaults reproduce the psychology
# channel verbatim; a channel on another niche overrides them in config's "editorial"
# block rather than forking this file.
EDITORIAL_DEFAULTS = {
    "cta": "Like and subscribe for more mind facts.",
    "item_noun": "psychology fact",
    "banned_topics": (
        "Dunning-Kruger, Pavlov's dogs, placebo effect, left/right brain, 10% of the "
        "brain, Maslow's pyramid, fight-or-flight basics"
    ),
    "banned_kinds": (
        "neutral perceptual/sensory trivia and brain-quirk curiosities with no emotional "
        "consequence (e.g. time-perception oddities, visual illusions, why clocks seem "
        "to freeze)"
    ),
    "stakes": (
        "their relationships, attraction, money, career, social status, self-image, or "
        "how other people secretly judge and treat them"
    ),
    "prefer": (
        "obscure named effects, weird well-replicated findings, forgotten experiments, "
        "everyday behaviors with hidden causes, things people do daily without knowing why"
    ),
    "strongest_angles": (
        "why people secretly like or dislike you, hidden signals you give off without "
        "knowing, invisible forces steering your money and decisions, persuasion and "
        "manipulation tactics quietly used on you every day, what your habits reveal about you"
    ),
    "hook_examples": (
        'Bad: "Psychology has many interesting effects." '
        'Good: "Your brain is lying to you right now." / "Why do you buy things you hate?"'
    ),
    # Injected verbatim as its own prompt block. Empty means "no house visual style",
    # which is the behaviour every channel had before this existed. A channel whose
    # identity depends on WHERE the footage looks like it was shot must set this:
    # left unset, the image model quietly defaults to Western subjects and settings.
    "visual_direction": "",
    # Injected verbatim as its own prompt block, after the standard script rules.
    # For channel-specific structural requirements (e.g. a mandatory closing beat)
    # that don't belong in the shared template. Empty means no extra rules.
    "extra_rules": "",
}


def editorial(config: dict) -> dict:
    """This channel's editorial rules: config overrides layered over the defaults."""
    return {**EDITORIAL_DEFAULTS, **(config.get("editorial") or {})}


def enforce_cta(script: str, cta: str = EDITORIAL_DEFAULTS["cta"]) -> str:
    """Guarantee the script ends with the exact CTA, replacing any drifted variant."""
    sentences = re.split(r"(?<=[.!?])\s+", script.strip())
    while sentences and re.search(r"\b(subscribe|like and)\b", sentences[-1], re.IGNORECASE):
        sentences.pop()
    sentences.append(cta)
    return " ".join(sentences)

RESEARCH_TEMPLATE = """You are the research lead for a viral faceless YouTube Shorts channel.

Niche: {niche}
Persona: {persona}
Today's date: {today}

Topics already covered (NEVER repeat or closely paraphrase these):
{history}

Live audience data from this channel's past uploads (real viewers voting with
their attention):
{performance}
Steer toward the emotional angle and sub-theme flavor of the overperformers and
away from the underperformers — but NEVER repeat or paraphrase a covered topic.

Task: silently consider several candidate findings from DIFFERENT sub-themes of the
niche (avoiding the sub-themes of the most recent topics above), then pick the ONE
best real, verifiable, little-known finding and extract its concrete details.

ABSOLUTE rule — real research only:
- The finding must come from actual published research or a documented real event.
  NEVER invent a study, an effect name, a number, or a detail. If you are not
  confident every detail below is real, pick a different finding you are sure of.
- The value of the video IS the specifics: who found it, what they actually did,
  and the exact result that sounds fake but is true. Vague knowledge is worthless.

CRITICAL selection rules:
- Obscurity is the product: most viewers must NEVER have heard of it. BANNED:
  anything a casual viewer knows from school, TikTok, or common self-help content
  (e.g. {banned_topics}). A famous topic is allowed ONLY via a buried detail or
  modern finding that flips it.
- Prefer: {prefer}.
- Direct personal stakes: {stakes}. The viewer should feel exposed, seen, or
  slightly alarmed — "this is about ME". BANNED: {banned_kinds}.
- Strongest angles: {strongest_angles}.

Return ONLY valid JSON, no markdown, exactly this shape:
{{
  "topic": "short internal label for the finding",
  "finding": "the finding in one plain sentence a 15-year-old instantly understands",
  "researchers": "who found or documented it (names or institution)",
  "year": "when",
  "method": "what the study or event actually involved, concretely: the setup, the participants, the strange detail of how it was done",
  "result": "the exact outcome with the specific number, percentage, or comparison that sounds fake but is true",
  "everyday_moment": "one concrete situation from the viewer's own daily life where this is operating on them, described in second person",
  "use_it": "one concrete thing the viewer can DO today to use, test, or beat this finding — a specific action with a visible result, never a platitude like 'be more confident'",
  "twist": "the counterintuitive kicker, open question, or dark implication that will fill the comments"
}}"""

PROMPT_TEMPLATE = """You are the head writer for a viral faceless YouTube Shorts channel.

Niche: {niche}
Persona: {persona}
Today's date: {today}

Your research lead already picked today's topic and verified the facts. This is
the ONLY source material; write strictly from it and never invent or embellish
beyond it:
{research}

Rules for the script:
- The script MUST deliver the specifics — the method's strange concrete detail,
  the exact result/number, and the everyday_moment — in plain spoken language.
  Mention the year and researchers only if it makes the script hit harder; one
  short phrase like "In 1971, researchers..." is enough.
- BANNED phrases: "studies show", "scientists say", "research suggests", or any
  vague appeal to authority. Name the thing itself instead.
- No jargon. Every sentence must be instantly understandable to a tired
  15-year-old scrolling in bed. If a term needs explaining, explain it in five
  words or cut it.
- Total length {target_words} words (~{target_seconds} seconds spoken).
- Sentence 1 is the HOOK and must be a direct question to the viewer OR a shocking
  claim, under 12 words, creating an instant curiosity gap. NEVER open with context,
  background, or a topic announcement. {hook_examples}
- Short punchy sentences. No filler, no "welcome back", no self-reference.
- Build the script around the unknown angle: open the curiosity gap, reveal the
  little-known fact as the payoff, then land ONE concrete "this is happening in your
  life right now" example so the viewer feels it personally.
- INTERACTIVE, not a lecture: after the payoff, talk WITH the viewer. Deliver the
  use_it action as a direct second-person instruction they can try today ("Next time
  you leave a conversation, ...") OR hit them with a direct question they will
  actually answer in the comments — ideally both. A video that only states facts
  fails; the viewer must leave with something to DO or something to SAY.
- Must be factually accurate and non-harmful. No medical/financial advice. Never
  invent or exaggerate a finding to make it more shocking — obscure but TRUE.
- Advertiser-friendly language only: no profanity, violence, sexual content, or
  shock-for-shock's-sake claims — the video must stay fully monetizable.
- Second-to-last beat: a twist, cliffhanger, or question that provokes comments.
- The FINAL sentence must be EXACTLY: "{cta}"
  Do not shorten it, reword it, or drop any word from it.
- Plain spoken text only: no emojis, no stage directions, no headers.
{extra_rules}
{visual_direction}
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
  "search_terms": ["5 stock-video search phrases (2-3 words each), IN CHRONOLOGICAL ORDER matching the script's narrative from hook to ending. Each must be a concrete filmable subject that exists in stock libraries (people, objects, places, actions) — never abstract concepts. e.g. 'woman thinking closeup', 'crowded subway station'"],
  "scene_prompts": ["5 illustration briefs, one per search term, SAME ORDER. Each describes the single picture that TEACHES what the script is saying during that scene: the subject, what they are doing, and the one visual detail that carries the point, so a viewer watching with the sound off still understands. Turn abstract ideas into physical metaphors. 15-25 words, present tense, no text or lettering in the picture. e.g. 'a man nods along happily with a salesman while faint puppet strings run from the salesman's fingers down to the man's arms'"]
}}"""

CRITIC_TEMPLATE = """You are a ruthless editor for a viral YouTube Shorts channel. A viewer
gives this script 1.5 seconds to earn attention and 40 seconds to teach them
something they'll retell at dinner. Judge it coldly.

Script:
{script}

The final call-to-action sentence is mandated channel policy: it will be there no
matter what, so judge everything EXCEPT that final sentence and never base a fail
on it.

Return ONLY valid JSON, no markdown, exactly this shape:
{{
  "learned": "the one concrete fact a viewer walks away with, stated plainly — empty string if there isn't one",
  "has_specifics": true or false — does it contain at least one real number, named study detail, or concrete experimental fact (not 'studies show'),
  "surprise": 1-10 — would a jaded viewer genuinely go "wait, WHAT?",
  "clarity": 1-10 — zero jargon, every sentence instantly understandable,
  "craving": 1-10 — does the ending make them want the next video and to comment,
  "interactive": 1-10 — does it speak TO the viewer and hand them something to DO (a concrete action to try today) or something to SAY (a question they would actually answer in the comments),
  "verdict": "pass" or "fail" — fail if has_specifics is false, or surprise < 7, or clarity < 7, or interactive < 7,
  "critique": "if fail: the 2-3 concrete changes that would fix it, referencing exact sentences"
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
    ed = editorial(config)
    qm = llm.quality_model(config)
    common = dict(
        niche=config["niche"],
        persona=config["channel_persona"],
        today=date.today().isoformat(),
    )

    # Pass 1 — research: pick one real finding and pin down its specifics.
    research_prompt = RESEARCH_TEMPLATE.format(
        performance=performance,
        history="\n".join(f"- {t}" for t in recent) if recent else "(none yet)",
        **common, **ed,
    )
    if forced_topic:
        research_prompt += f"\n\nOverride: the finding MUST be about: {forced_topic}"
    research = llm.generate_json(research_prompt, config, model=qm)
    print(f"    research: {research.get('topic')} | {str(research.get('result'))[:90]}")

    # Pass 2 — write the script strictly from the researched facts.
    write_prompt = PROMPT_TEMPLATE.format(
        research=json.dumps(research, indent=2, ensure_ascii=False),
        target_words=int(target_seconds * 2.6),
        target_seconds=target_seconds,
        playlists=", ".join(config.get("playlists", ["Mind Facts"])),
        **common, **ed,
    )
    plan = llm.generate_json(write_prompt, config, model=qm)

    # Pass 3 — critic gate: one revision round; the gate itself must never
    # break an unattended run, so any failure here ships the current draft.
    try:
        review = llm.generate_json(
            CRITIC_TEMPLATE.format(script=plan.get("script", "")), config, model=qm)
        if str(review.get("verdict", "pass")).strip().lower() == "pass":
            print(f"    critic: pass | learns: {str(review.get('learned'))[:90]}")
        else:
            print(f"    critic: fail | {str(review.get('critique'))[:180]}")
            retry_prompt = write_prompt + (
                "\n\nYour previous draft FAILED editorial review. The review:\n"
                + json.dumps(review, indent=2, ensure_ascii=False)
                + "\nRewrite the video fixing every point in the critique. "
                  "Same JSON shape, all the same rules.")
            plan = llm.generate_json(retry_prompt, config, model=qm)
    except Exception as exc:
        print(f"    critic gate skipped: {exc}")
    for key in ("topic", "title", "description", "tags", "script", "search_terms"):
        if key not in plan:
            raise RuntimeError(f"LLM plan missing key: {key}")
    plan["script"] = enforce_cta(plan["script"], ed["cta"])
    if "#shorts" not in plan["title"].lower():
        plan["title"] = plan["title"].rstrip() + " #Shorts"
    return plan

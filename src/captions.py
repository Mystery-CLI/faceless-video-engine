"""Burned-in animated captions (.ass): words pop in as a group, and each word
lights up in the highlight color at the exact moment it is spoken (karaoke sweep)."""


def _ts(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int(seconds % 3600 // 60)
    s = seconds % 60
    return f"{h}:{m:02d}:{s:05.2f}"


# PrimaryColour is the color a word turns AS IT IS SPOKEN (karaoke fill);
# SecondaryColour is the color before it's spoken.
HEADER = """[Script Info]
ScriptType: v4.00+
PlayResX: {play_w}
PlayResY: {play_h}
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Word,{font},{size},{highlight},{primary},&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,9,4,5,60,60,760,1
Style: Hook,{font},{hook_size},{hook_color},&H00FFFFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,12,6,8,70,70,{hook_margin},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def build_ass(words: list, config: dict, out_path, hook: str | None = None) -> None:
    cap = config.get("captions", {})
    vid = config.get("video", {})
    play_w, play_h = int(vid.get("width", 1080)), int(vid.get("height", 1920))
    chunk_size = int(cap.get("words_per_chunk", 3))
    header = HEADER.format(
        play_w=play_w,
        play_h=play_h,
        font=cap.get("font", "Arial Black"),
        size=int(cap.get("font_size", 88)),
        primary=cap.get("primary_color", "&H00FFFFFF"),
        highlight=cap.get("highlight_color", "&H0000D7FF"),
        hook_size=int(cap.get("hook_font_size", 96)),
        hook_color=cap.get("hook_color", "&H0023A6F5"),  # brand gold, ASS is BGR
        hook_margin=int(play_h * 0.16),  # top third on any canvas
    )
    lines = []

    # Hook title card: the opening frame doubles as the video's thumbnail in the
    # channel grid and search (Shorts don't support custom thumbnails), so flash
    # the hook big and bold in the top third for the first beat.
    if hook and cap.get("hook_card", True):
        card = (r"{\fscx80\fscy80\t(0,120,\fscx104\fscy104)"
                r"\t(120,200,\fscx100\fscy100)\fad(0,220)}")
        lines.append(
            f"Dialogue: 1,{_ts(0)},{_ts(1.25)},Hook,,0,0,0,,{card}{hook.upper()}"
        )
    for i in range(0, len(words), chunk_size):
        chunk = words[i:i + chunk_size]
        start = chunk[0]["start"]
        # hold the chunk on screen until the next chunk begins so text never flickers
        next_chunk = words[i + chunk_size:i + chunk_size + 1]
        end = next_chunk[0]["start"] if next_chunk else chunk[-1]["end"] + 0.5

        # karaoke: \k durations are in centiseconds, relative to the line start
        parts = []
        for j, w in enumerate(chunk):
            if j + 1 < len(chunk):
                dur = chunk[j + 1]["start"] - w["start"]
            else:
                dur = w["end"] - w["start"]
            k = max(1, round(dur * 100))
            sep = " " if j + 1 < len(chunk) else ""
            parts.append(f"{{\\k{k}}}{w['word'].upper()}{sep}")

        # pop-in: fade + spring from 70% to 105% to 100% scale
        intro = (r"{\fad(60,0)\fscx70\fscy70"
                 r"\t(0,90,\fscx106\fscy106)\t(90,150,\fscx100\fscy100)}")
        lines.append(f"Dialogue: 0,{_ts(start)},{_ts(end)},Word,,0,0,0,,{intro}{''.join(parts)}")
    out_path.write_text(header + "\n".join(lines) + "\n", encoding="utf-8")

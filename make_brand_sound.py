"""Generate original sonic-logo candidates for the channel's audio signature.

100% synthesized from sine tones + envelopes + echo, so the sound is entirely
yours: copyright-free, claim-proof, and free. Each is ~1.6s and is meant to sit
quietly UNDER the opening hook of every video as a recognizable audio fingerprint.

Run:  python make_brand_sound.py   ->  assets/brand/sonic_logo_{1,2,3}.mp3
"""
import subprocess
from pathlib import Path

BRAND = Path(__file__).resolve().parent / "assets" / "brand"
BRAND.mkdir(parents=True, exist_ok=True)


def gen(name: str, inputs: list, filtergraph: str, dur: float) -> None:
    args = ["ffmpeg", "-y"]
    for i in inputs:
        args += ["-f", "lavfi", "-i", i]
    args += ["-filter_complex", filtergraph, "-map", "[out]", "-t", f"{dur}",
             "-ac", "2", "-ar", "44100", "-c:a", "libmp3lame", "-q:a", "4",
             str(BRAND / name)]
    subprocess.run(args, check=True, capture_output=True)
    print("wrote", name)


# Candidate 1 — "Spark": ascending arpeggio D5 -> A5 -> D6 over a warm sub.
# Feels like a flash of realization. Best match for a mind-facts channel.
gen("sonic_logo_1.mp3",
    ["sine=frequency=587:duration=0.6",
     "sine=frequency=880:duration=0.6",
     "sine=frequency=1175:duration=0.8",
     "sine=frequency=147:duration=1.5"],
    "[0]afade=t=in:d=0.02,afade=t=out:st=0.28:d=0.25,volume=0.55[a0];"
    "[1]adelay=160|160,afade=t=in:d=0.02,afade=t=out:st=0.32:d=0.25,volume=0.55[a1];"
    "[2]adelay=320|320,afade=t=in:d=0.02,afade=t=out:st=0.5:d=0.45,volume=0.7[a2];"
    "[3]afade=t=in:d=0.35,afade=t=out:st=1.0:d=0.5,volume=0.3[a3];"
    "[a0][a1][a2][a3]amix=inputs=4:normalize=0,aecho=0.8:0.7:65:0.25,"
    "loudnorm=I=-17:TP=-2,afade=t=out:st=1.35:d=0.4[out]",
    1.7)

# Candidate 2 — "Pulse": minimal and mysterious. A low swell with two soft sub
# pulses, resolved by a single bright ping. Understated, cinematic.
gen("sonic_logo_2.mp3",
    ["sine=frequency=110:duration=1.2",
     "sine=frequency=220:duration=0.5",
     "sine=frequency=1319:duration=0.7"],
    "[0]afade=t=in:d=0.4:curve=squ,afade=t=out:st=0.9:d=0.3,volume=0.5,"
    "tremolo=f=5:d=0.5[a0];"
    "[1]adelay=120|120,afade=t=in:d=0.05,afade=t=out:st=0.25:d=0.2,volume=0.35[a1];"
    "[2]adelay=520|520,afade=t=in:d=0.02,afade=t=out:st=0.45:d=0.4,volume=0.55[a2];"
    "[a0][a1][a2]amix=inputs=3:normalize=0,aecho=0.8:0.7:90:0.3,"
    "loudnorm=I=-17:TP=-2,afade=t=out:st=1.3:d=0.4[out]",
    1.7)

# Candidate 3 — "Shimmer": a warm major chord (C5+E5+G5) swelling in, capped by a
# high chime. Fuller and calmer, leans premium/reflective.
gen("sonic_logo_3.mp3",
    ["sine=frequency=523:duration=1.0",
     "sine=frequency=659:duration=1.0",
     "sine=frequency=784:duration=1.0",
     "sine=frequency=1047:duration=0.7"],
    "[0]afade=t=in:d=0.3,afade=t=out:st=0.7:d=0.4,volume=0.4[a0];"
    "[1]afade=t=in:d=0.3,afade=t=out:st=0.7:d=0.4,volume=0.35[a1];"
    "[2]afade=t=in:d=0.3,afade=t=out:st=0.7:d=0.4,volume=0.35[a2];"
    "[3]adelay=300|300,afade=t=in:d=0.03,afade=t=out:st=0.5:d=0.4,volume=0.55[a3];"
    "[a0][a1][a2][a3]amix=inputs=4:normalize=0,aecho=0.8:0.7:80:0.3,"
    "loudnorm=I=-17:TP=-2,afade=t=out:st=1.35:d=0.4[out]",
    1.7)

print("done — listen and pick your signature")

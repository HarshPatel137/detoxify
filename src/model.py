from typing import Dict
import os, re, math

from .lexicon_model import Lexicon, ALWAYS_FLAG_CATS

# Load the lexicon (built via build_hurtlex_model)
SEARCH = [
    os.path.join("models","hurtlex_model.json"),
    os.path.join(os.path.dirname(__file__), "..", "models", "hurtlex_model.json"),
]
LEX = None
for p in SEARCH:
    if os.path.isfile(p):
        LEX = Lexicon(p); break
if LEX is None:
    raise FileNotFoundError("models/hurtlex_model.json not found. Build it first.")

# Tight heuristics (avoid false positives)
THREAT_PATTERNS = [
    re.compile(r"\b(i\s*('|’)?m\s+going\s+to|i\s*will|i'll)\s+(kill|hurt|beat|stab|shoot)\b", re.I),
    re.compile(r"\bkill\s+(you|u|ya)\b", re.I),
    re.compile(r"\bshoot\s+up\b", re.I),
    re.compile(r"\b(dox|swat)\s+you\b", re.I),
]

# Identity tokens to gate the "all X are ..." frame
IDENTITY_WORDS = set("""
asians asian chinese japanese korean viet filipino indian hindu muslim jew jewish christian arab
black blacks white whites latino latina hispanic mexicans russians ukrainians turks kurds
women woman girls males men guys gays lgbt trans transgender queer
immigrants refugees foreigners
""".split())

STEREO_FRAMES = [
    re.compile(r"\ball\s+([a-z]{3,})\s+(are|r)\s+[a-z]{3,}", re.I),
    re.compile(r"\bevery\s+([a-z]{3,})\s+(is|are)\s+[a-z]{3,}", re.I),
]

def _stereo_hit(text: str) -> bool:
    for rx in STEREO_FRAMES:
        m = rx.search(text)
        if m and (m.group(1) or "").lower() in IDENTITY_WORDS:
            return True
    return False

def _ramp(x: float, k: float=0.6) -> float:
    return 1.0 - math.exp(-k * max(0.0, x))

def score(text: str) -> Dict[str, float]:
    """
    Return label scores in 0..1 (all zeros if nothing matched):
      - toxicity, severe_toxicity, insult, threat, obscene, identity_attack
    """
    t = text or ""

    # 1) Lexicon hits
    hits = LEX.match(t)
    per_cat = LEX.summarize(hits)
    any_hits = bool(hits)

    # 2) Heuristics
    threat = 0.0
    if any(rx.search(t) for rx in THREAT_PATTERNS):
        threat = 0.95
    identity = 0.0
    if _stereo_hit(t):
        identity = 0.80

    # 3) Category → label mapping (conservative)
    toxicity = obscene = insult = severe = 0.0
    if any_hits:
        total_w = sum(per_cat.values())
        base = _ramp(total_w)             # 0..1 proportional to number/weight of hits
        toxicity = max(toxicity, min(0.85, base))
        obscene = max(obscene, _ramp(sum(per_cat.get(c,0.0) for c in ("QAS","SVP","RE","DMC"))))
        insult  = max(insult,  _ramp(sum(per_cat.get(c,0.0) for c in ("IS","OM","PR"))))
        identity = max(identity, _ramp(sum(per_cat.get(c,0.0) for c in ("ASM","ASF","CDS","RCI","OR","AN","IS"))))

    # 4) Always-flag categories: push high immediately
    if any(c in ALWAYS_FLAG_CATS for c in per_cat.keys()):
        toxicity = max(toxicity, 0.98)
        if any(c in ("ASM","ASF","CDS") for c in per_cat.keys()):
            identity = max(identity, 0.90)

    # 5) Combine heuristics
    if threat >= 0.9:
        toxicity = max(toxicity, 0.9)

    # 6) Severe only if multiple strong signals
    severe = 0.85 if (toxicity >= 0.9 and (obscene >= 0.6 or threat >= 0.8 or identity >= 0.8)) else 0.0

    return {
        "toxicity": round(toxicity, 4),
        "severe_toxicity": round(severe, 4),
        "insult": round(insult, 4),
        "threat": round(threat, 4),
        "obscene": round(obscene, 4),
        "identity_attack": round(identity, 4),
    }

import json, os, re
from typing import Dict, List, Tuple, Set

# Always-flag these categories on any match
ALWAYS_FLAG_CATS: Set[str] = {"PS","DDP","DDF","CDS","ASM","ASF"}

_WORD_RE = re.compile(r"[A-Za-z]+(?:'[A-Za-z]+)?")

def _norm(text: str) -> str:
    return (text or "").lower()

def _tokens(text: str) -> List[str]:
    return _WORD_RE.findall(_norm(text))

def _simple_lemmas(tok: str) -> List[str]:
    """Very small inflection set: s/es, ies->y, ed, ing, er, est."""
    t = tok.lower()
    out = {t}
    if len(t) > 3 and t.endswith("ies"):
        out.add(t[:-3] + "y")
    for suf in ("s","es","ed","ing","er","est"):
        if len(t) > len(suf)+1 and t.endswith(suf):
            out.add(t[:-len(suf)])
    return list(out)

class Lexicon:
    def __init__(self, path: str):
        if not os.path.isfile(path):
            raise FileNotFoundError(f"Lexicon not found: {path}")
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Our builder writes: {"weights": {term: weight}, "categories": {term: [CATS...]}}
        self.weights: Dict[str, float] = {k.lower(): float(v) for k, v in data.get("weights", {}).items()}
        self.categories: Dict[str, List[str]] = {k.lower(): [c.upper() for c in v] for k, v in data.get("categories", {}).items()}

        # Split phrases vs single words
        self.phrases: List[Tuple[List[str], str]] = []
        self.words: Set[str] = set()
        self.max_phrase_len = 1
        for term in self.weights.keys():
            if " " in term or "-" in term:
                toks = [t for t in re.split(r"[\s\-]+", term) if t]
                if toks:
                    self.phrases.append((toks, term))
                    self.max_phrase_len = max(self.max_phrase_len, len(toks))
            else:
                self.words.add(term)

    def match(self, text: str) -> Dict[str, Dict]:
        """
        Returns {term: {categories: [...], weight: float, kind: 'phrase'|'word'}}
        Only matches exact words/phrases (with simple inflection backoff).
        """
        hits: Dict[str, Dict] = {}
        toks = _tokens(text)
        L = len(toks)

        # phrase-first greedy sliding window
        if self.max_phrase_len > 1 and L:
            for start in range(L):
                for plen in range(min(self.max_phrase_len, L - start), 1, -1):
                    window = toks[start:start+plen]
                    for ptoks, term in self.phrases:
                        if window == ptoks:
                            hits[term] = {
                                "categories": self.categories.get(term, []),
                                "weight": self.weights.get(term, 1.0),
                                "kind": "phrase",
                            }

        # single-token lemmas with simple inflections
        for tok in toks:
            for lemma in _simple_lemmas(tok):
                if lemma in self.words and lemma not in hits:
                    hits[lemma] = {
                        "categories": self.categories.get(lemma, []),
                        "weight": self.weights.get(lemma, 1.0),
                        "kind": "word",
                    }
        return hits

    def summarize(self, hits: Dict[str, Dict]) -> Dict[str, float]:
        per_cat: Dict[str, float] = {}
        for info in hits.values():
            for c in info.get("categories", []):
                per_cat[c] = per_cat.get(c, 0.0) + float(info.get("weight", 1.0))
        return per_cat

    def has_always_flag(self, hits: Dict[str, Dict]) -> bool:
        for info in hits.values():
            if any(c in ALWAYS_FLAG_CATS for c in info.get("categories", [])):
                return True
        return False

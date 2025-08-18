"""
Compile a category‑aware HurtLex model from the EN lemma file.

Works with .tsv / .csv / .tsv.gz / .csv.gz, header or no header.
Usage:
  python -m src.training.build_hurtlex_model --tsv /path/to/hurtlex_EN.tsv[.gz] [--force]
"""
import os, json, argparse, re, csv, gzip, io, sys
from collections import Counter

KNOWN = {"PS","RCI","PA","DDF","DDP","DMC","IS","OR","AN","ASM","ASF","PR","OM","QAS","CDS","RE","SVP"}
UPPER_CODE = re.compile(r"\b([A-Z]{2,3})\b")

def _open_any(path: str):
    if path.endswith(".gz"):
        return io.TextIOWrapper(gzip.open(path, "rb"), encoding="utf-8", errors="ignore")
    return open(path, "r", encoding="utf-8", errors="ignore")

def _sniff(sample: str) -> str:
    try:
        return csv.Sniffer().sniff(sample, delimiters="\t,;,").delimiter
    except Exception:
        if "\t" in sample: return "\t"
        if "," in sample: return ","
        return ";"

def read_lemma_file(path: str):
    with _open_any(path) as f:
        sample = f.read(4096)
        f.seek(0)
        delim = _sniff(sample)
        rdr = csv.reader(f, delimiter=delim)
        rows = [r for r in rdr if any((c or "").strip() for c in r)]

    header = [c.strip().lower() for c in rows[0]] if rows else []
    has_header = any(x in header for x in ("lemma","lexeme","category","categories","pos","stereotype","id"))
    if has_header:
        rows = rows[1:]

    lemma_idx = None
    cats_idx = None
    for i, name in enumerate(header):
        if name in ("lemma","lexeme"): lemma_idx = i
        if name in ("category","categories"): cats_idx = i

    terms = {}
    for r in rows:
        # lemma
        if lemma_idx is not None and lemma_idx < len(r) and (r[lemma_idx] or "").strip():
            lemma = r[lemma_idx].strip().lower()
        else:
            toks = [c for c in r if re.search(r"[A-Za-z]", c or "")]
            if not toks: continue
            lemma = toks[0].strip().lower()

        # categories
        cats = set()
        if cats_idx is not None and cats_idx < len(r):
            for tok in re.split(r"[\s,;/]+", (r[cats_idx] or "").strip()):
                tok = (tok or "").strip().upper()
                if tok in KNOWN: cats.add(tok)

        if not cats:
            line = " ".join([c or "" for c in r])
            cats |= set(m.group(1) for m in UPPER_CODE.finditer(line) if m.group(1) in KNOWN)

        if lemma and cats:
            terms.setdefault(lemma, set()).update(cats)

    return {k: sorted(v) for k, v in terms.items() if v}

def build_model(term2cats):
    weights = {}
    for term, cats in term2cats.items():
        w = 1.0
        if any(c in {"DMC","QAS","SVP","RE"} for c in cats): w += 0.5
        if any(c in {"ASM","ASF"} for c in cats): w += 1.0
        if any(c in {"PS","DDP","DDF","CDS"} for c in cats): w += 1.5
        if " " in term or "-" in term: w += 0.5
        weights[term] = w
    return {"kind":"hurtlex-lexicon","version":3,"weights":weights,"categories":term2cats}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tsv", required=True, help="Path to HurtLex EN lemma file (.tsv/.csv/.gz)")
    ap.add_argument("--out", default=os.path.join("models","hurtlex_model.json"))
    ap.add_argument("--force", action="store_true", help="Write even if small (<100 terms)")
    args = ap.parse_args()

    term2cats = read_lemma_file(args.tsv)
    print(f"Parsed {len(term2cats)} lemmas.")
    c = Counter(cat for cats in term2cats.values() for cat in cats)
    print("Top categories:", c.most_common(8))

    if len(term2cats) < 100 and not args.force:
        sys.exit("Parsed <100 terms; pass --force if using a tiny subset, or check the TSV path/format.")

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(build_model(term2cats), f, ensure_ascii=False)
    print(f"Saved {args.out}")

if __name__ == "__main__":
    main()

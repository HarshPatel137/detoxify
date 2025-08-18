"""Coordinates normalize → score → threshold check and assembles reasons for the UI. 
Keeps the hot path small and easy to test."""

from .lexicon_model import score as lex_score

def load_model(): return 'hurtlex'

def predict_proba(texts):
    return [lex_score(t) for t in texts]

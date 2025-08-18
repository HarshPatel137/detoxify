# Toxicity Coach (Lite)

[![build](https://img.shields.io/github/actions/workflow/status/<HarshPatel137>/<toxicity-coach>/ci.yml?label=CI)](https://github.com/<HarshPatel137>/<toxicity-coach>/actions)
![python](https://img.shields.io/badge/Python-3.10%2B-3B82F6)
![license](https://img.shields.io/badge/License-MIT-green)

A lightweight **Discord bot** that nudges conversations toward civility.

**Highlights**
- Lexicon-based detection (HurtLex); *no heavy ML deps*
- Always-flag categories: `PS, DDP, DDF, CDS, ASM, ASF`
- Whole-word + simple inflections & phrase support
- Threat & stereotype heuristics (“I will …”, “all X are …”)
- Private heads-up tools: *Why flagged, Delete, Breathing, Blackjack*
- Slash commands: `/toxicity status`, `/toxicity policy`, `/blackjack`

## Demos

**Private heads-up (only you see it)**  
[![Watch heads-up demo](docs/thumb-headsup.png)](docs/demo-heads-up.mp4?raw=1)  
https://github.com/user-attachments/assets/f2dea24c-3b74-4da8-8694-712f5439ffa2

_Explains why a message was flagged, offers Delete / Breathing / Blackjack cool-down._

**Slash commands**  
[![Watch commands demo](docs/thumb-commands.png)](docs/demo-commands.mp4?raw=1)  
https://github.com/user-attachments/assets/9f097abc-fb8c-4e52-a47c-6c6962297fcf
`/toxicity status` shows a civility meter & CSV; `/toxicity policy` edits per-channel thresholds.

## Quickstart
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
scripts/build_model.sh /path/to/hurtlex_EN.tsv
cp .env.example .env   # paste your token
python -m src.bot

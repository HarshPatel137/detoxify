from dataclasses import dataclass
import os
from dotenv import load_dotenv
load_dotenv()

@dataclass
class Settings:
    token: str
    triage_channel_id: int | None
    retention_days: int

def _to_int(x):
    try: return int(x) if x else None
    except: return None

SETTINGS = Settings(
    token=os.getenv("DISCORD_TOKEN",""),
    triage_channel_id=_to_int(os.getenv("TRIAGE_CHANNEL_ID")),
    retention_days=int(os.getenv("RETENTION_DAYS","30"))
)

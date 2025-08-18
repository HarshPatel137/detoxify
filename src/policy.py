from typing import Dict
from .storage import get_threshold
DEFAULTS={'toxicity':0.50,'severe_toxicity':0.40,'insult':0.45,'threat':0.35,'obscene':0.45,'identity_attack':0.35}
def decide_action(guild_id:str, channel_id:str, scores:Dict[str,float]):
    over=False; details={}
    for k,v in scores.items():
        thr=get_threshold(guild_id,channel_id,k) or DEFAULTS.get(k,0.5)
        flag=v>=thr; details[k]={'score':v,'threshold':thr,'over':flag}; over=over or flag
    return over, details

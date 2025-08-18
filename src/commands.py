"""
Slash-command layer (presentation only).

what?:
  - /toxicity status  → shows personal civility meter + recent stats (ephemeral)
  - /toxicity policy  → view/set thresholds with safe defaults (per-channel overrides)
  - /blackjack        → quick cool-down mini-game (ephemeral)
"""

import io, discord
from discord import app_commands
from .storage import fetch_recent_user_scores, upsert_policy, get_threshold
from .utils import csv_export
from .labels import LABELS
from .policy import DEFAULTS

def _respect_score(rows):
    if not rows:
        return 100.0, 0.0, 0.0
    vals = [sc.get("toxicity", 0.0) for _, sc in rows]
    avg = sum(vals) / max(1, len(vals))
    return max(0.0, min(100.0, (1.0 - avg) * 100.0)), avg, (max(vals) if vals else 0.0)

def _meter(score, width=20):
    filled = int(round((score / 100.0) * width))
    return "█" * filled + "░" * (width - filled)

sNICE = {
    "toxicity": "Overall toxic tone",
    "severe_toxicity": "Severely toxic",
    "insult": "Insulting",
    "threat": "Threatening",
    "obscene": "Obscene",
    "identity_attack": "Identity attack",
}

def _embed_thr(gid, cid, title="Toxicity policy"):
    vals = {lab: get_threshold(gid, cid, lab) or DEFAULTS.get(lab, 0.5) for lab in LABELS}
    e = discord.Embed(title=title, color=0x3B82F6)
    for k in LABELS:
        e.add_field(name=NICE.get(k, k), value=f"{vals[k]:.2f}", inline=True)
    e.set_footer(text="Defaults tuned for HurtLex; you can override per channel.")
    return e

class ThresholdModal(discord.ui.Modal, title="Set custom threshold (0..1)"):
    def __init__(self, cb, label_key: str):
        super().__init__()
        self.cb = cb
        self.label_key = label_key
        self.value_input = discord.ui.TextInput(label=NICE.get(label_key, label_key), placeholder="e.g., 0.30")
        self.add_item(self.value_input)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            v = float(str(self.value_input.value).strip())
        except:
            await interaction.response.send_message("Enter 0..1", ephemeral=True)
            return
        await self.cb(interaction, self.label_key, max(0.0, min(1.0, v)))

class PolicySetView(discord.ui.View):
    def __init__(self, gid: str, cid: str, can_edit: bool):
        super().__init__(timeout=180)
        self.gid = gid
        self.cid = cid
        self.can_edit = can_edit
        self.selected = None
        for lab in LABELS:
            self.add_item(self.LabelBtn(self, lab))
        for v in [0.30, 0.40, 0.50, 0.60, 0.70, 0.80]:
            self.add_item(self.ThreshBtn(self, v))
        self.add_item(self.CustomBtn(self))

    def _header(self):
        sel = f"Selected: **{self.selected or '—'}**"
        e = discord.Embed(title="Set a threshold", description=sel, color=0x10B981 if self.can_edit else 0xEF4444)
        if not self.can_edit:
            e.set_footer(text="Need Manage Messages here to edit.")
        return e

    async def _save(self, inter, label, thr):
        if not self.can_edit:
            await inter.response.send_message("Need Manage Messages.", ephemeral=True)
            return
        upsert_policy(self.gid, self.cid, label, thr)
        await inter.response.edit_message(embed=_embed_thr(self.gid, self.cid, "Saved ✓"), view=PolicyHomeView(self.gid, self.cid))

    class LabelBtn(discord.ui.Button):
        def __init__(self, p, label_key):
            super().__init__(label=label_key, style=discord.ButtonStyle.secondary)
            self.p = p
            self.k = label_key

        async def callback(self, inter):
            self.p.selected = self.k
            await inter.response.edit_message(embed=self.p._header(), view=self.p)

    class ThreshBtn(discord.ui.Button):
        def __init__(self, p, v):
            super().__init__(label=f"{v:.2f}", style=discord.ButtonStyle.primary)
            self.p = p
            self.v = v

        async def callback(self, inter):
            if not self.p.selected:
                await inter.response.send_message("Pick a label first ↓", ephemeral=True)
                return
            await self.p._save(inter, self.p.selected, float(self.v))

    class CustomBtn(discord.ui.Button):
        def __init__(self, p):
            super().__init__(label="Custom…", style=discord.ButtonStyle.success)
            self.p = p

        async def callback(self, inter):
            if not self.p.selected:
                await inter.response.send_message("Pick a label first ↓", ephemeral=True)
                return

            async def done(i, label, thr):
                await self.p._save(i, label, thr)

            await inter.response.send_modal(ThresholdModal(done, self.p.selected))

class PolicyHomeView(discord.ui.View):
    def __init__(self, gid, cid):
        super().__init__(timeout=120)
        self.gid = gid
        self.cid = cid

    @discord.ui.button(label="Set threshold", emoji="🛠️", style=discord.ButtonStyle.primary)
    async def set_btn(self, inter, _):
        can_edit = getattr(inter.user, "guild_permissions", None) and inter.user.guild_permissions.manage_messages
        view = PolicySetView(str(inter.guild_id), str(inter.channel_id), bool(can_edit))
        await inter.response.edit_message(embed=view._header(), view=view)

class ToxicityCommands(app_commands.Group):
    def __init__(self):
        super().__init__(name="toxicity", description="Toxicity Coach commands")

    @app_commands.command(name="status", description="Your 7-day Respect Score (private)")
    async def status(self, inter: discord.Interaction):
        rows = fetch_recent_user_scores(str(inter.user.id), str(inter.guild_id))
        s, avg, peak = _respect_score(rows)
        e = discord.Embed(title="Your Respect Score", color=0x10B981 if s >= 75 else 0xF59E0B if s >= 60 else 0xEF4444)
        e.add_field(name=f"{s:.0f} / 100", value=f"`{_meter(s)}`", inline=False)
        e.add_field(name="Avg (7d)", value=f"{avg:.2f}", inline=True)
        e.add_field(name="Peak (7d)", value=f"{peak:.2f}", inline=True)
        file = discord.File(fp=io.BytesIO(csv_export(rows)), filename="toxicity-trend.csv")
        await inter.response.send_message("Here’s your 7-day snapshot (CSV attached).", embed=e, file=file, ephemeral=True)

    @app_commands.command(name="policy", description="View or set thresholds for this channel")
    async def policy(self, inter: discord.Interaction):
        await inter.response.send_message(
            embed=_embed_thr(str(inter.guild_id), str(inter.channel_id)),
            view=PolicyHomeView(str(inter.guild_id), str(inter.channel_id)),
            ephemeral=True,
        )

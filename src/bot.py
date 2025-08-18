"""
Bot entrypoint & event wiring.

what?:
  - Configures intents & Client, syncs the slash-command tree, sets presence.
  - Listens for messages; runs fast local scoring; if flagged → shows a private
    heads-up panel to the author with actions (Why/Delete/Breathe/Blackjack).

why?:
  - Keeps Discord plumbing isolated from scoring & UI so those parts can evolve
    independently (swap model, change UI) without touching the event loop.

KEY IDEAS:
  - privacy-first (no uploads), instant cold-start, ephemeral moderation (no public shaming)
  - rate-limit scoring to avoid reprocessing every keystroke on busy channels
"""

import asyncio, time, random, discord
from typing import Dict, List, Tuple
from discord.ext import commands, tasks
from .config import SETTINGS
from .model import score
from .storage import record_message, purge_older_than
from .commands import ToxicityCommands

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
bot = commands.Bot(command_prefix="!", intents=intents)

RATE_LIMIT_SECONDS = 1.5
_last_scored: Dict[int, float] = {}

COLOR_OK = 0x10B981
COLOR_INFO = 0x3B82F6
COLOR_WARN = 0xF59E0B
COLOR_ALERT = 0xEF4444


async def _delete_later(msg: discord.Message, seconds: int = 20):
    try:
        await asyncio.sleep(seconds)
        await msg.delete()
    except Exception:
        pass


# -----------------------------
# Blackjack (private mini-game)
# -----------------------------
SUITS = ["♠", "♥", "♦", "♣"]
RANKS = ["A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K"]


def _new_deck() -> List[str]:
    return [f"{r}{s}" for s in SUITS for r in RANKS]


def _hand_total(cards: List[str]) -> Tuple[int, bool]:
    """
    Return (best_total, is_blackjack) where best_total is the highest <= 21,
    or the smallest total if all exceed 21. Aces can be 1 or 11.
    """
    vals = []
    for c in cards:
        r = c[:-1]  # rank is everything but last char (suit)
        if r in ("J", "Q", "K"):
            vals.append(10)
        elif r == "A":
            vals.append(11)
        else:
            vals.append(int(r))
    total = sum(vals)
    # Downgrade Aces from 11 to 1 as needed
    aces = sum(1 for c in cards if c[:-1] == "A")
    while total > 21 and aces > 0:
        total -= 10
        aces -= 1
    is_blackjack = (len(cards) == 2 and total == 21)
    return total, is_blackjack


def _result_text(player: List[str], dealer: List[str]) -> Tuple[str, int]:
    """Return (result_text, color)."""
    pt, pbj = _hand_total(player)
    dt, dbj = _hand_total(dealer)
    if pt > 21:
        return "💥 You busted. Dealer wins.", COLOR_ALERT
    if dt > 21:
        return "🎉 Dealer busted. **You win!**", COLOR_OK
    if pbj and not dbj:
        return "🃏 **Blackjack! You win!**", COLOR_OK
    if dbj and not pbj:
        return "🃏 Dealer has blackjack. You lose.", COLOR_ALERT
    if pt > dt:
        return "✅ **You win!**", COLOR_OK
    if pt < dt:
        return "❌ Dealer wins.", COLOR_ALERT
    return "➖ Push (tie).", COLOR_WARN


def _cards_str(cards: List[str]) -> str:
    return "  ".join(cards)


class BlackjackView(discord.ui.View):
    def __init__(self, author_id: int):
        super().__init__(timeout=300)
        self.author_id = author_id
        self.deck = _new_deck()
        random.shuffle(self.deck)
        self.player: List[str] = []
        self.dealer: List[str] = []
        self.round_over = False
        self.revealed = False
        self._start_round()

    # ----- helpers -----
    def _draw(self) -> str:
        if not self.deck:
            self.deck = _new_deck()
            random.shuffle(self.deck)
        return self.deck.pop()

    def _start_round(self):
        self.player = [self._draw(), self._draw()]
        self.dealer = [self._draw(), self._draw()]
        self.round_over = False
        self.revealed = False

    def _dealer_play(self):
        self.revealed = True
        # Dealer draws to 17+ (with ace adjustment)
        while True:
            total, _ = _hand_total(self.dealer)
            if total >= 17:
                break
            self.dealer.append(self._draw())
        self.round_over = True

    def _author_only(self, inter: discord.Interaction) -> bool:
        if inter.user.id != self.author_id:
            asyncio.create_task(
                inter.response.send_message(
                    "This game is private to the original user.",
                    ephemeral=True,
                )
            )
            return False
        return True

    # ----- rendering -----
    def _embed(self) -> discord.Embed:
        pt, pbj = _hand_total(self.player)
        if self.revealed:
            dt, dbj = _hand_total(self.dealer)
            dealer_line = f"{_cards_str(self.dealer)}  (**{dt}**)"
        else:
            # hide dealer's second card
            shown = [self.dealer[0], "🂠"]
            dt_partial, _ = _hand_total([self.dealer[0]])
            dealer_line = f"{_cards_str(shown)}  (showing **{dt_partial}**)"

        title = "♣️ Blackjack"
        desc = (
            f"**Your hand**: {_cards_str(self.player)}  (**{pt}**)\n"
            f"**Dealer**: {dealer_line}"
        )

        if self.round_over and self.revealed:
            res, color = _result_text(self.player, self.dealer)
        else:
            color = COLOR_INFO
            res = "Hit or Stand. Dealer draws to 17+."

        e = discord.Embed(title=title, description=desc, color=color)
        e.set_footer(text="Aces count as 1 or 11. New Round resets hands.")
        if self.round_over and self.revealed:
            e.add_field(name="Result", value=res, inline=False)
        return e

    def _freeze(self):
        # Disable Hit/Stand when round is over
        for item in self.children:
            if isinstance(item, discord.ui.Button) and item.custom_id in ("bj_hit", "bj_stand"):
                item.disabled = True

    def _thaw(self):
        for item in self.children:
            if isinstance(item, discord.ui.Button) and item.custom_id in ("bj_hit", "bj_stand"):
                item.disabled = False

    # ----- buttons -----
    @discord.ui.button(label="Hit", style=discord.ButtonStyle.primary, custom_id="bj_hit")
    async def hit(self, inter: discord.Interaction, _):
        if not self._author_only(inter):
            return
        if self.round_over:
            await inter.response.edit_message(embed=self._embed(), view=self)
            return
        self.player.append(self._draw())
        pt, _ = _hand_total(self.player)
        if pt > 21:
            # player busts, dealer reveals to finalize UI
            self._dealer_play()
            self._freeze()
        await inter.response.edit_message(embed=self._embed(), view=self)

    @discord.ui.button(label="Stand", style=discord.ButtonStyle.secondary, custom_id="bj_stand")
    async def stand(self, inter: discord.Interaction, _):
        if not self._author_only(inter):
            return
        if not self.round_over:
            self._dealer_play()
            self._freeze()
        await inter.response.edit_message(embed=self._embed(), view=self)

    @discord.ui.button(label="New Round", style=discord.ButtonStyle.success, custom_id="bj_new")
    async def new_round(self, inter: discord.Interaction, _):
        if not self._author_only(inter):
            return
        self._start_round()
        self._thaw()
        await inter.response.edit_message(embed=self._embed(), view=self)

    @discord.ui.button(label="Close", style=discord.ButtonStyle.danger, custom_id="bj_close")
    async def close(self, inter: discord.Interaction, _):
        if not self._author_only(inter):
            return
        await inter.response.edit_message(content="Blackjack closed. 🎴", embed=None, view=None)


# -----------------------------
# Heads-up (private tools)
# -----------------------------
class HeadsUpPanel(discord.ui.View):
    def __init__(self, author_id: int, root_id: int, original_message_id: int, channel_id: int, explain_text: str):
        super().__init__(timeout=180)
        self.author_id = author_id
        self.root_id = root_id
        self.msg_id = original_message_id
        self.chan_id = channel_id
        self.explain = explain_text

    async def _guard(self, inter: discord.Interaction) -> bool:
        if inter.user.id != self.author_id:
            await inter.response.send_message("This panel is private to the original user.", ephemeral=True)
            return False
        return True

    async def _edit(self, inter: discord.Interaction, *, embed=None, view=None):
        await inter.response.defer(ephemeral=True, thinking=False)
        await inter.followup.edit_message(message_id=self.root_id, embed=embed, view=view)

    @discord.ui.button(label="Why flagged?", emoji="🔎", style=discord.ButtonStyle.secondary)
    async def why(self, inter: discord.Interaction, _):
        if not await self._guard(inter):
            return
        await self._edit(
            inter,
            embed=discord.Embed(title="Why your message was flagged", description=self.explain, color=COLOR_WARN),
            view=self,
        )

    @discord.ui.button(label="Delete my message", emoji="🗑️", style=discord.ButtonStyle.danger)
    async def delete_msg(self, inter: discord.Interaction, _):
        if not await self._guard(inter):
            return
        try:
            ch = await bot.fetch_channel(self.chan_id)
            if isinstance(ch, (discord.TextChannel, discord.Thread)):
                m = await ch.fetch_message(self.msg_id)
                await m.delete()
                await self._edit(
                    inter,
                    embed=discord.Embed(
                        title="Deleted", description="Your message was removed. Thanks for the reset 🙏", color=COLOR_OK
                    ),
                    view=self,
                )
                return
        except discord.Forbidden:
            await inter.response.send_message("I need **Manage Messages** here to delete.", ephemeral=True)
            return
        except Exception:
            pass
        await inter.response.send_message("Couldn't delete (maybe already removed).", ephemeral=True)

    @discord.ui.button(label="Start 60s Box Breathing", emoji="🫁", style=discord.ButtonStyle.success)
    async def breathing(self, inter: discord.Interaction, _):
        if not await self._guard(inter):
            return
        phases = [("Inhale 4", 4), ("Hold 4", 4), ("Exhale 4", 4), ("Hold 4", 4)]
        total = 0
        while total < 60:
            for text, sec in phases:
                total += sec
                await self._edit(
                    inter,
                    embed=discord.Embed(
                        title="Take a breath", description=f"🫁 **Box breathing**: {text}  ({total}s/60s)", color=COLOR_INFO
                    ),
                    view=self,
                )
                await asyncio.sleep(sec)
        await self._edit(
            inter, embed=discord.Embed(title="Nice reset", description="✅ Done — you can continue or close.", color=COLOR_OK), view=self
        )

    @discord.ui.button(label="Play Blackjack", emoji="🃏", style=discord.ButtonStyle.primary)
    async def blackjack(self, inter: discord.Interaction, _):
        if not await self._guard(inter):
            return
        game = BlackjackView(author_id=inter.user.id)
        await inter.response.send_message(embed=game._embed(), view=game, ephemeral=True)

    @discord.ui.button(label="Close", emoji="❌", style=discord.ButtonStyle.danger)
    async def close(self, inter: discord.Interaction, _):
        if not await self._guard(inter):
            return
        await inter.response.defer(ephemeral=True, thinking=False)
        try:
            await inter.followup.delete_message(message_id=self.root_id)
        except Exception:
            await inter.followup.edit_message(message_id=self.root_id, content="Heads-up dismissed. Take care ✨", embed=None, view=None)


class OpenPanelStub(discord.ui.View):
    def __init__(self, author_id: int, message_id: int, channel_id: int, explain_text: str):
        super().__init__(timeout=30)
        self.author_id = author_id
        self.message_id = message_id
        self.channel_id = channel_id
        self.explain = explain_text
        self.bound = None

    def bind(self, msg: discord.Message):
        self.bound = msg

    async def _author_only(self, inter: discord.Interaction) -> bool:
        if inter.user.id != self.author_id:
            await inter.response.send_message("Only the author can view details.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="View details (private)", emoji="👀", style=discord.ButtonStyle.primary)
    async def open(self, inter: discord.Interaction, _):
        if not self._author_only(inter):
            return
        try:
            if self.bound:
                await self.bound.delete()
        except Exception:
            pass
        await inter.response.send_message(
            embed=discord.Embed(
                title="Take a breath",
                description=("Looks heated — see why it was flagged and get quick tools (private)."),
                color=COLOR_INFO,
            ),
            ephemeral=True,
        )
        root = await inter.original_response()
        panel = HeadsUpPanel(
            author_id=inter.user.id,
            root_id=root.id,
            original_message_id=self.message_id,
            channel_id=self.channel_id,
            explain_text=self.explain,
        )
        await inter.edit_original_response(view=panel)


# -----------------------------
# Bot lifecycle + scoring
# -----------------------------
@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} (guilds={len(bot.guilds)})")
    try:
        bot.tree.add_command(ToxicityCommands())
        await bot.tree.sync()
    except Exception as e:
        print("Command sync error:", e)
    retention_cleaner.start()


@tasks.loop(hours=24)
async def retention_cleaner():
    try:
        purge_older_than(30)
    except Exception as e:
        print("Purge error:", e)


def _explain(details: Dict) -> str:
    names = {
        "toxicity": "overall toxic tone",
        "severe_toxicity": "severely toxic content",
        "insult": "insulting language",
        "threat": "threatening language",
        "obscene": "obscene language",
        "identity_attack": "identity-based attack",
    }
    parts = [f"- **{names.get(k, k).title()}**: {v['score']:.2f} ≥ {v['threshold']:.2f}" for k, v in details.items() if v.get("over")]
    return "\n".join(parts) or "- Nothing exceeded configured limits."


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot or not message.guild:
        return
    now = time.time()
    if now - _last_scored.get(message.author.id, 0) < RATE_LIMIT_SECONDS:
        return
    _last_scored[message.author.id] = now

    content = message.content or ""
    if not content.strip():
        return

    try:
        from .policy import decide_action
        scores = score(content)
        triggered, per_label = decide_action(str(message.guild.id), str(message.channel.id), scores)
    except Exception:
        return

    record_message(
        str(message.id),
        str(message.author.id),
        str(message.channel.id),
        str(message.guild.id),
        scores,
        1 if triggered else 0,
    )

    if triggered:
        view = OpenPanelStub(
            author_id=message.author.id, message_id=message.id, channel_id=message.channel.id, explain_text=_explain(per_label)
        )
        stub = await message.reply(
            embed=discord.Embed(
                title="Calm down — this looks heated",
                description=("Click **View details** to privately see why it was flagged and get quick tools. Only you will see the next screen."),
                color=COLOR_ALERT,
            ),
            view=view,
            mention_author=False,
            silent=True,
            suppress_embeds=True,
        )
        view.bind(stub)
        asyncio.create_task(_delete_later(stub, 20))

    await bot.process_commands(message)


if __name__ == "__main__":
    if not SETTINGS.token:
        raise SystemExit("Set DISCORD_TOKEN in .env")
    bot.run(SETTINGS.token)

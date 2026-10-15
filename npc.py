"""npc.py - NPC brain: personality, mood, trust, memory, and game actions."""
import json
import os
import re
from llm import ask_json
from memory import MemoryStore, SUMMARY_EVERY_TURNS

_store = None  # shared SQLite store, one per game session


def get_store():
    global _store
    if _store is None:
        _store = MemoryStore()
    return _store
from world import QUEST_TRUST, GATE_TRUST, TASK_TRUST_MIRA, TASK_TRUST_REX

try:
    from voice import text_mood as _voice_mood  # VADER-backed sentiment (optional but installed)
except Exception:
    _voice_mood = None

POS = ("please", "thank", "sorry", "hello", "hey", "namaste", "good", "help", "respect", "honest",
       "friend", "sir", "apprec", "nice", "dhanyavad", "shukriya")
NEG = ("stupid", "idiot", "hate", "fool", "useless", "steal", "stole", "ugly", "worst", "shut")
BOASTS = ("greatest", "i am a hero", "richest", "i killed", "i am the king")


def tier(trust):
    """Named relationship tier (idea adapted from npc-dialogue-system, MIT).
    Shown on the rumor map, /status and the demo — judges read tiers, not numbers."""
    try:
        t = int(trust)
    except (TypeError, ValueError):
        return "Stranger"
    if t >= 60:
        return "Trusted"
    if t >= 30:
        return "Liked"
    if t >= 10:
        return "Known"
    if t <= -30:
        return "Hostile"
    if t < 0:
        return "Wary"
    return "Stranger"


class NPC:
    def __init__(self, name, role, personality, speech_style, backstory,
                 secret="", actions=None, color=(200, 200, 200), pos=(0, 0)):
        self.name = name
        self.role = role
        self.personality = personality
        self.speech_style = speech_style
        self.backstory = backstory
        self.secret = secret
        self.actions = actions or {}      # {action_name: when to use it}
        self.color = color
        self.pos = pos                    # tile position (used by the game)

        self.trust = 0                    # -100 .. +100
        self.mood = "neutral"
        self.memories = []                # short-term buffer only (last few facts)
        self.history = []                 # last turns; summarized to SQLite, never sent whole
        self.store = None                 # attached MemoryStore (long-term DB)
        self.game_day = 1
        self._saved_memories: list[str] = []  # facts already persisted to SQLite
        self.last_voice: dict | None = None   # vocal-expression read of the last turn
        self.last_offline = False   # True when the last reply came from the built-in fallback

    # ---------- prompts ----------
    def _system_prompt(self) -> str:
        action_lines = "\n".join(f'  - "{k}": {v}' for k, v in self.actions.items()) or "  (none)"
        return f"""You are {self.name}, a {self.role} in a small Minecraft-style fantasy village.

Personality: {self.personality}
Speech style: {self.speech_style}
Backstory: {self.backstory}
Your secret (NEVER reveal it unless your trust in the player is 60 or higher): {self.secret}

RULES:
- Stay fully in character. Never mention being an AI, a model, or a game.
- Keep replies short: 1 to 3 sentences.
- The player may write in English, Hinglish or a Kannada-English mix. Reply in the player's style.
- Your attitude depends on your trust in the player and your mood.
- Be skeptical of boasts and lies. Reward honesty and kindness.
- Follow the GAME STATE rules given in each message about when you may use an action.

Actions you can trigger (use "none" if no action applies):
{action_lines}

Respond ONLY with JSON in exactly this format:
{{
  "reply": "what you say out loud",
  "mood": "one word, e.g. happy, angry, suspicious, curious, neutral",
  "trust_change": integer between -15 and 15,
  "learned_fact": "a short fact about the player that you learned, or null",
  "action": "none" or one of the action names above
}}"""

    def _long_context(self, player_text: str) -> str:
        """What enters the prompt: rolling profile + latest daily summary +
        top-k retrieved facts + nothing else. Full history is never sent."""
        if self.store is None:
            mems = "\n".join(f"- {m}" for m in self.memories[-8:]) or "- (nothing yet)"
            return f"What you know about the player:\n{mems}"
        prof = self.store.rolling(self.name)
        summ = self.store.latest_summary(self.name)
        facts = self.store.retrieve(self.name, player_text)
        parts = []
        if prof:
            parts.append(f"Your lasting impression of the player: {prof}")
        if summ:
            parts.append(f"Yesterday's summary: {summ}")
        parts.append("Relevant memories:\n" + ("\n".join(f"- {f}" for f in facts) if facts else "- (nothing yet)"))
        return "\n".join(parts)

    def _user_prompt(self, player_text: str, game_context: str) -> str:
        history = "\n".join(self.history[-8:]) or "(this is the start of the conversation)"
        return f"""Current trust in player: {self.trust} (scale -100 to 100)
Current mood: {self.mood}

GAME STATE:
{game_context or '(nothing special)'}

{self._long_context(player_text)}

Recent conversation (short-term only):
{history}

Player says: "{player_text}"
"""

    # ---------- main action ----------
    def talk(self, player_text: str, game_context: str = "", voice: dict | None = None):
        """Returns (reply_text, action). Falls back to built-in replies if the AI is unavailable.
        voice: optional voice.analyze()/listen_once() dict -> expression adjusts trust + mood
        BEFORE world.py validates the action. See npc.last_voice for what was detected."""
        data = ask_json(self._system_prompt(), self._user_prompt(player_text, game_context))
        if isinstance(data, dict) and "reply" in data:
            self.last_offline = False
        else:
            self.last_offline = True
            data = self._offline_data(player_text, game_context)
        data = self._merge_voice(data, voice)
        out = self._apply(data, player_text)
        self._persist()
        return out

    def _merge_voice(self, data, voice):
        """Fold vocal expression into the turn. Never raises; game rules still decide."""
        self.last_voice = None
        if not isinstance(voice, dict) or voice.get("error"):
            return data
        label = str(voice.get("label") or "neutral")
        try:
            conf = float(voice.get("confidence", 0.0))
        except (TypeError, ValueError):
            conf = 0.0
        try:
            delta = max(-8, min(8, int(voice.get("trust_delta", 0))))
        except (TypeError, ValueError):
            delta = 0
        try:
            data["trust_change"] = max(-15, min(15, int(float(data.get("trust_change", 0))) + delta))
        except (TypeError, ValueError):
            pass
        if conf >= 0.65 and voice.get("mood"):
            data["mood"] = str(voice["mood"])
        if conf >= 0.5 and label != "neutral":
            note = f"[voice sounded {label}]"
            fact = str(data.get("learned_fact") or "").strip()
            data["learned_fact"] = (f"{fact} {note}".strip() if fact and fact.lower() != "null" else note)
        self.last_voice = {"label": label, "trust_delta": delta, "confidence": round(conf, 2),
                           "mood": str(data.get("mood", ""))}
        return data

    def _persist(self):
        """Save this turn to SQLite; auto-summarize every N turns. Never raises."""
        if self.store is None:
            return
        try:
            if self.memories and (not self._saved_memories or self.memories[-1] != self._saved_memories[-1]):
                self.store.add_fact(self.name, self.memories[-1])
                self._saved_memories.append(self.memories[-1])
            since = self.store.bump_turns(self.name, self.game_day)
            if since >= SUMMARY_EVERY_TURNS:
                self.store.summarize_npc(self, self.history, ask_json, self.game_day)
        except Exception:
            pass

    def _apply(self, data, player_text):
        try:
            change = max(-15, min(15, int(float(data.get("trust_change", 0)))))
        except (TypeError, ValueError):
            change = 0
        self.trust = max(-100, min(100, self.trust + change))
        self.mood = str(data.get("mood") or self.mood)

        fact = data.get("learned_fact")
        if fact and str(fact).lower() != "null" and str(fact).strip():
            self.memories.append(str(fact).strip()[:300])
            del self.memories[:-8]  # short-term buffer stays bounded; rest lives in SQLite

        action = str(data.get("action") or "none")
        if action not in self.actions:
            action = "none"

        reply = str(data["reply"])
        self.history.append(f"Player: {player_text}")
        self.history.append(f"{self.name}: {reply}")
        del self.history[:-8]
        return reply, action

    def status(self) -> str:
        db = f", db_facts={self.store.fact_count(self.name)}" if self.store else " (no DB)"
        mems = "\n".join(f"  - {m}" for m in self.memories) or "  (none)"
        summ = ""
        if self.store and self.store.latest_summary(self.name):
            summ = f"\nlast summary: {self.store.latest_summary(self.name)[:200]}"
        return f"[{self.name}] trust={self.trust} ({tier(self.trust)}) mood={self.mood} day={self.game_day}{db}\nrecent:\n{mems}{summ}"

    # ---------- offline fallback (keeps the game playable without AI) ----------
    def _offline_data(self, player_text, game_context):
        low = player_text.lower()
        words = re.findall(r"[a-z']+", low)
        pos = sum(1 for w in words if w.startswith(POS))
        neg = sum(1 for w in words if w.startswith(NEG)) + (1 if "shut up" in low else 0)
        boast = any(b in low for b in BOASTS)
        vader = _voice_mood(player_text) if _voice_mood else 0.0  # VADER compound in [-1, 1]
        change = min(10, pos * 5) - min(15, neg * 8) - (5 if boast else 0)
        change += 3 if vader > 0.5 else (-3 if vader < -0.3 else 0)
        change = max(-15, min(10, change))
        if change == 0 and words:
            change = 1
        mood = ("angry" if neg or vader < -0.5 else "suspicious" if boast
                else "warm" if (pos or vader > 0.5) else self.mood)
        m = re.search(r"my name is (\w+)", low)
        fact = f"The player says their name is {m.group(1).capitalize()}" if m else None
        reply, action = self._offline_reply(low, neg, self.trust + change, game_context)
        return {"reply": reply, "mood": mood, "trust_change": change, "learned_fact": fact, "action": action}

    def _offline_reply(self, low, neg, trust, ctx):
        has = lambda *ks: any(k in low for k in ks)
        n = self.name
        if neg:
            return {"Gruff": "Watch your tongue, or the door's right there.",
                    "Rex": "Careful. Insult a guard again and you'll spend the night in the cells.",
                    "Mira": "Well! No need to be rude, darling. Rude customers pay extra."}.get(n, "That was rude."), "none"
        if n == "Gruff":
            if has("ore", "iron") and has("brought", "here", "got", "found", "done", "have"):
                return "Good iron. Fine quality. Take this sword. You've earned it.", "complete_quest"
            if has("quest", "work", "job", "task", "help", "kaam"):
                if trust >= QUEST_TRUST:
                    return "Hmph. I need Iron Ore from the Old Forest, past Rex's gate. Bring it back.", "give_quest"
                return "Work? I don't hand tasks to strangers. Earn my trust first.", "none"
            return ("Ah, you. What do you need?" if trust >= 30 else "State your business. I've got iron to hammer."), "none"
        if n == "Rex":
            if has("gate", "pass", "open", "forest", "let me", "andar"):
                if trust >= GATE_TRUST:
                    return "You seem honest enough. The gate is open. Stay safe out there.", "open_gate"
                return "The gate stays shut. I don't know you yet. Be honest and respectful.", "none"
            if has("lit", "done", "finished", "report", "complete"):
                return "Braziers burning? Let me verify, soldier.", "complete_task_rex"
            if has("task", "work", "job", "patrol", "brazier", "prove", "discipline", "duty"):
                if trust >= TASK_TRUST_REX:
                    return "Discipline it is. Three watch braziers went dark — light them all, then report.", "give_task_rex"
                return "Duties are earned, civilian. Show me respect first.", "none"
            return "Halt. State your name and purpose.", "none"
        if n == "Mira":
            price = re.search(r"costs (\d+) gold", ctx or "")
            price = price.group(1) if price else "20"
            if has("brought", "got them", "here they", "done", "return", "petals", "flowers", "count them"):
                return "Moonpetals! Let me count them, darling.", "complete_task_mira"
            if has("quest", "work", "job", "task", "help", "kaam", "errand", "flower", "petal"):
                if trust >= TASK_TRUST_MIRA:
                    return "An errand, darling? My potions need 3 moonpetals — glowing flowers. Fetch them!", "give_task_mira"
                return "Errands are for friends, darling. Charm me first.", "none"
            if has("price", "cost", "how much"):
                return f"For you, darling? {price} gold. An absolute bargain!", "none"
            if has("buy", "potion", "purchase", "deal", "take", "yes"):
                return "Wonderful choice, darling! One healing potion, coming up.", "sell_potion"
            return "Come, come, darling! The finest healing potions in the village!", "none"
        return "...", "none"


def load_npcs(path=None):
    path = path or os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "npcs.json")
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    store = get_store()  # one shared SQLite DB for the whole village
    npcs = {
        name: NPC(name=name, role=d["role"], personality=d["personality"],
                  speech_style=d["speech_style"], backstory=d["backstory"],
                  secret=d.get("secret", ""), actions=d.get("actions", {}),
                  color=tuple(d["color"]), pos=tuple(d["pos"]))
        for name, d in raw.items()
    }
    for n in npcs.values():
        n.store = store
    return npcs

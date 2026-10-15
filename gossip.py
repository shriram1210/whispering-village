"""gossip.py - Stage 3: nightly NPC-to-NPC rumor exchange.

Each night, villagers who trust each other share one memory about the player.
The retelling distorts through the speaker's personality (rules below, or one
LLM call per pair when online). The listener believes it in proportion to how
much they trust the speaker, and their opinion of the player shifts.

Design: deterministic, quota-safe, offline-first. The game calls run_night()
with llm_fn=None (instant rule path); the engine also accepts an LLM reteller.
"""
import json
import os
import random
import re

TALK_THRESHOLD = 40    # relationships at/above this talk at night
MAX_MEMORIES = 8       # short-term buffer stays bounded (matches npc.py)

_POS = ("kind", "help", "generous", "honest", "brave", "saved", "gave", "paid", "friend")
_NEG = ("stol", "lied", "lying", "rude", "cheat", "attack", "threat", "refus", "terrible")


def load_relationships(path=None):
    path = path or os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "relationships.json")
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {"Mira": {"Gruff": 60, "Rex": 40}, "Gruff": {"Mira": 50, "Rex": 60},
                "Rex": {"Mira": 30, "Gruff": 60}}


def _double_numbers(text):
    return re.sub(r"\d+", lambda m: str(int(m.group(0)) * 2), text)


_UPGRADE = (("good", "amazing"), ("nice", "incredible"), ("bad", "terrible"),
            ("big", "enormous"), ("small", "tiny"), ("a lot", "a fortune"))


def distort(speaker, text):
    """Rule-based retelling in the speaker's voice. Pure function, no I/O."""
    text = (text or "").strip()
    if speaker == "Mira":
        for a, b in _UPGRADE:
            text = re.sub(r"\b" + a + r"\b", b, text, flags=re.IGNORECASE)
        return _double_numbers(text) + ", darling — mark my words"
    if speaker == "Gruff":
        words = text.split()
        short = " ".join(words[:12])
        return "They say " + short[0].lower() + short[1:] + ". Hmph." if short else "Hmph."
    if speaker == "Rex":
        return "Report (unverified): " + text + " — under observation."
    return text


def _sentiment_nudge(text):
    low = (text or "").lower()
    if any(w in low for w in _NEG):
        return -2
    if any(w in low for w in _POS):
        return 2
    return 0


def _retell_llm(llm_fn, speaker, personality, memory):
    """One LLM call per pair. Returns (retold, used_llm). Never raises."""
    try:
        data = llm_fn(
            f"Retell this village rumor the way {speaker} would: {personality}. "
            'Reply ONLY with JSON: {"retold": "...", "sentiment": "good|bad|neutral"}',
            f"Rumor: {memory}")
    except Exception:
        return distort(speaker, memory), False
    if isinstance(data, dict) and data.get("retold"):
        return str(data["retold"])[:300], True
    return distort(speaker, memory), False


def run_night(npcs, relationships, world=None, llm_fn=None, rng=None, threshold=TALK_THRESHOLD):
    """Run one night of gossip. Returns {"msgs": [...]} for the feed.

    npcs: dict name->NPC (needs .memories, .trust, .store or None).
    relationships: {speaker: {listener: 0-100}}.
    world: optional; day+1 and rumor_edges[(s,l)] = day are recorded.
    rng: random.Random for tests (default: global random).
    """
    rng = rng or random
    day = (world.day + 1) if world else 1
    if world:
        world.day = day
    msgs = [f"Night {day} falls. Villagers exchange rumors."]
    if world is not None:
        world.rumor_edges = getattr(world, "rumor_edges", {})
    for speaker, targets in relationships.items():
        if speaker not in npcs:
            continue
        for listener, rel in targets.items():
            if listener not in npcs or listener == speaker:
                continue
            if rel < threshold:
                continue
            if rng.random() < 0.15:
                continue  # some nights they just sleep
            speaker_npc = npcs[speaker]
            memory = speaker_npc.memories[-1] if speaker_npc.memories else ""
            if not memory:
                msgs.append(f"{speaker} has nothing to share.")
                continue
            if llm_fn is not None:
                retold, _ = _retell_llm(llm_fn, speaker,
                                        getattr(speaker_npc, "personality", ""), memory)
            else:
                retold = distort(speaker, memory)
            listener_npc = npcs[listener]
            belief = max(1.0, min(10.0, 5.0 * rel / 100.0))
            fact = f"Heard from {speaker}: {retold}"
            listener_npc.memories.append(fact)
            del listener_npc.memories[:-MAX_MEMORIES]
            if listener_npc.store is not None:
                try:
                    listener_npc.store.add_fact(listener, fact, belief, kind="gossip")
                except Exception:
                    pass
            nudge = _sentiment_nudge(retold)
            if nudge:
                listener_npc.trust = max(-100, min(100, listener_npc.trust + nudge))
            if world is not None:
                world.rumor_edges[(speaker, listener)] = day
            msgs.append(f"{speaker} → {listener}: \"{retold[:90]}\"")
    return {"msgs": msgs, "day": day}

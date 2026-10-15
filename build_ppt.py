"""build_ppt.py - generates Whispering_Village_Hackathon.pptx (16:9, twilight theme)."""
import os
from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN

HERE = os.path.dirname(os.path.abspath(__file__))
BG = RGBColor(20, 22, 36)
GOLD = RGBColor(255, 220, 110)
WHITE = RGBColor(240, 240, 245)
GREY = RGBColor(150, 150, 170)
GREEN = RGBColor(110, 225, 130)

prs = Presentation()
prs.slide_width = Inches(13.333)
prs.slide_height = Inches(7.5)
BLANK = prs.slide_layouts[6]


def slide():
    s = prs.slides.add_slide(BLANK)
    s.background.fill.solid()
    s.background.fill.fore_color.rgb = BG
    tx = s.shapes.add_textbox(Inches(0.4), Inches(7.05), Inches(12.5), Inches(0.35))
    tx.text_frame.text = "Whispering Village  •  Cognitive NPCs — Conversational Dialogue Systems"
    for p in tx.text_frame.paragraphs:
        p.alignment = PP_ALIGN.RIGHT
        for r in p.runs:
            r.font.size = Pt(10)
            r.font.color.rgb = GREY
    return s


def title(s, text, size=36):
    tx = s.shapes.add_textbox(Inches(0.6), Inches(0.3), Inches(12.1), Inches(1.0))
    p = tx.text_frame.paragraphs[0]
    p.text = text
    r = p.runs[0]
    r.font.size = Pt(size)
    r.font.bold = True
    r.font.color.rgb = GOLD


def bullets(s, items, left=0.7, top=1.6, width=11.9, size=20, gap=60):
    tx = s.shapes.add_textbox(Inches(left), Inches(top), Inches(width), Inches(5.0))
    tf = tx.text_frame
    tf.word_wrap = True
    for i, (head, sub) in enumerate(items):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.space_after = Pt(10 if sub else 14)
        p.space_before = Pt(gap / 10 if False else 0)
        rh = p.add_run()
        rh.text = ("•  " if not sub else "•  " + head + "  ")
        rh.font.size = Pt(size)
        rh.font.bold = True
        rh.font.color.rgb = GREEN if False else WHITE
        if sub:
            rs = p.add_run()
            rs.text = sub
            rs.font.size = Pt(size)
            rs.font.color.rgb = WHITE
    return tx


def image_right(s, path, w=5.6):
    full = os.path.join(HERE, path)
    if not os.path.exists(full):
        return
    s.shapes.add_picture(full, Inches(13.333 - w - 0.5), Inches(1.5), width=Inches(w))


# 1. Title
s = slide()
t = s.shapes.add_textbox(Inches(0.6), Inches(1.6), Inches(12.1), Inches(1.4))
p = t.text_frame.paragraphs[0]
p.alignment = PP_ALIGN.CENTER
r = p.add_run()
r.text = "Whispering Village"
r.font.size = Pt(60)
r.font.bold = True
r.font.color.rgb = GOLD
t2 = s.shapes.add_textbox(Inches(0.6), Inches(3.1), Inches(12.1), Inches(0.8))
p = t2.text_frame.paragraphs[0]
p.alignment = PP_ALIGN.CENTER
r = p.add_run()
r.text = "Cognitive NPCs that remember, gossip, and change the game"
r.font.size = Pt(26)
r.font.color.rgb = WHITE
t3 = s.shapes.add_textbox(Inches(0.6), Inches(4.4), Inches(12.1), Inches(1.6))
p = t3.text_frame.paragraphs[0]
p.alignment = PP_ALIGN.CENTER
r = p.add_run()
r.text = "Innovation Mission 5  •  Conversational Dialogue Systems  •  48-hour Hackathon\nTeam of 4  •  Pygame + Gemini + SQLite  •  Pure software build"
r.font.size = Pt(20)
r.font.color.rgb = GREY

# 2. Problem
s = slide()
title(s, "Problem Statement")
bullets(s, [
    ("Mission 5: Cognitive NPCs.", "Build game characters that hold natural conversations instead of fixed dialogue trees."),
    ("Stage 1 — Foundation:", "an NPC that takes free-text input and replies in character."),
    ("Stage 2 — Functional:", "conversations must change quests, prices, objectives, progression."),
    ("Stage 3 — Innovation:", "memory, personality and adaptive behaviour across sessions."),
    ("Constraint:", "pure software, 48 hours, basic project/API experience, demo-or-die reliability."),
])

# 3. Solution
s = slide()
title(s, "Our Solution: a Village That Talks Back")
bullets(s, [
    ("Gruff the blacksmith —", "gruff, honest, hates liars. Gives the Iron-Ore quest at trust ≥ 20."),
    ("Mira the merchant —", "chatty gossip who sells potions; prices react to trust (30% off friends, +50% enemies)."),
    ("Rex the guard —", "strict gatekeeper; opens the Old Forest gate at trust ≥ 15, slams it at ≤ −30."),
    ("Core loop:", "explore → talk in natural language (or voice) → AI suggests → game validates → NPC remembers."),
    ("Golden rule:", "the AI suggests, the game decides — no invented rewards, no skipped quests."),
])

# 4. Architecture
s = slide()
title(s, "Architecture")
bullets(s, [
    ("Pygame client (main.py + art.py) —", "twilight 2D world, dialogue panel, trust bar, portraits, mic button; AI calls on background threads."),
    ("npc.py —", "personality prompts, mood/trust/memory state, structured JSON replies, offline fallback when AI is down."),
    ("world.py —", "map, quest state, gate, shop pricing; validates every AI-proposed action against trust thresholds."),
    ("memory.py + SQLite —", "FTS5 facts, daily summaries, rolling profile; prompt = profile + summary + top-k facts."),
    ("voice.py —", "mic → speech-to-text → prosody analysis → vocal expression → trust delta."),
    ("Secrets:", "API key lives only in backend .env — never in the game or repo."),
])

# 5. Stage 1
s = slide()
title(s, "Stage 1 — Foundation: One NPC That Talks")
bullets(s, [
    ("Free-text chat", "with Gruff in the terminal (chat_terminal.py) — no fixed options."),
    ("Strict JSON contract:", '{ reply, mood, trust_change (−15…15), learned_fact, action }.'),
    ("In-character + multilingual:", "gruff forge-voice; understands Hinglish/code-switched input, mirrors the player's style."),
    ("Trust from tone:", "boasts punished, apologies rewarded — verified live against Gemini."),
])

# 6. Stage 2 + screenshot
s = slide()
title(s, "Stage 2 — Functional: Talk Changes the World")
bullets(s, [
    ("Dialogue-driven quest:", "earn Gruff's trust → fetch Iron Ore past Rex's gate → Iron Sword + 30 gold."),
    ("Living economy:", "Mira's potion price follows her opinion of you."),
    ("Consequences:", "insult Rex and the gate slams shut; be polite and it opens."),
    ("Demo-proof:", "every rule unit-tested with stubbed AI (quest gating, pricing, gate lock, bad-AI guard)."),
], width=6.6)
image_right(s, "stage2_headless_shot.png", w=5.9)

# 7. Uniqueness
s = slide()
title(s, "Uniqueness: a Rumor-Immunity Simulator")
bullets(s, [
    ("Real-world problem:", "misinformation spreads faster than facts (Bad News game, N=15k, Nature)."),
    ("Our twist:", "the Stage-3 gossip engine that spreads lies between NPCs becomes the mechanic that teaches verification."),
    ("Quest:", "Rex plants a fake ‘poisoned well’ rumor — the quest completes only after cross-checking with 2 NPCs."),
    ("Second layer:", "Hinglish merchant = low-pressure language practice (Duolingo Max precedent); empathy-gated quests reward kindness."),
    ("Pitch line:", "“The NPC doesn't just parse words — the village teaches you whom to trust.”"),
])

# 8. Voice + screenshot
s = slide()
title(s, "Voice Expression Detection")
bullets(s, [
    ("Pipeline:", "mic → free speech-to-text → numpy prosody (pitch, energy, pace, pauses, jitter) → expression."),
    ("7 expressions:", "kind, genuine, overconfident, nervous, sad, rude, deceptive — each moves trust (−6…+6)."),
    ("Research-backed cues:", "rising pitch + slow = uncertain; raised pitch-max + hesitations = shifty."),
    ("UI:", "mic button + V key, pulsing REC dot, transcript arrives as ‘You (voice, kind): …’."),
    ("Fallbacks:", "no mic / offline → typed text; per-player calibration for personal thresholds."),
], width=6.6)
image_right(s, "mic_proof.png", w=5.9)

# 9. Memory
s = slide()
title(s, "Persistent Memory That Scales")
bullets(s, [
    ("Problem:", "10,000 conversations can't fit in a prompt — so we never send history."),
    ("Design:", "short-term buffer (last 8 turns) + SQLite long-term: FTS5 facts, daily summaries, rolling profile."),
    ("Nightly reflection:", "each in-game day, every NPC dreams the day into durable facts (Generative-Agents pattern)."),
    ("Retrieval:", "relevance + importance + recency → top-4 facts per reply; proven persistent across restarts."),
])

# 10. Demo
s = slide()
title(s, "Live Demo (3 minutes)")
bullets(s, [
    ("1. Talk:", "greet Gruff, tell him your name — he remembers it after a restart."),
    ("2. Quest:", "earn trust, take the Iron-Ore quest, convince Rex, fetch the glowing ore."),
    ("3. Voice:", "speak kindly to Mira (trust jumps) vs arrogantly to Rex (gate stays shut)."),
    ("4. Memory:", "/sleep → NPCs summarize the day; /status shows the diary."),
    ("5. Rumor:", "verify Rex's well rumor with two villagers to complete the immunity quest."),
])

# 11. Thanks
s = slide()
title(s, "Thank You")
bullets(s, [
    ("Stack:", "Python + Pygame + Gemini + SQLite — all free-tier, all offline-capable."),
    ("Proof:", "unit-tested rules, headless render tests, live-API verified, check_api.py diagnostics."),
    ("Next:", "full rumor map UI, pixel-font polish, Vosk offline speech-to-text."),
    ("Whispering Village —", "where every conversation changes the game."),
])

out = os.path.join(HERE, "Whispering_Village_Hackathon.pptx")
prs.save(out)
print("saved:", out, "| slides:", len(list(prs.slides)))

"""chat_terminal.py - Stage 1 preserved: talk to Gruff in the terminal.

Stage 2's main.py is the Pygame village. This file keeps the
original terminal loop working (no Pygame needed).
Uses the same npc.py + llm.py, so offline fallback works here too.
Commands: /status  /quit
"""
from npc import load_npcs

WELCOME = """Whispering Village — Stage 1: talk to Gruff the blacksmith.
Commands: /status (trust/mood/memories)  /quit (exit)
"""


def main():
    from world import World
    npcs = load_npcs()
    world = World(npcs)
    print(WELCOME)
    print("Gruff: Hmph. Another visitor. State yer business.\n")
    print("(Tip: /sleep ends the day — Gruff summarizes what he learned into his diary.)\n")
    npc = npcs["Gruff"]
    while True:
        try:
            msg = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGruff: Off with ye, then.")
            break
        if not msg:
            continue
        if msg == "/quit":
            print("Gruff: Mind the forge smoke on yer way out.")
            break
        if msg == "/status":
            print(npc.status())
            continue
        if msg == "/sleep":
            for m in world.advance_day():
                print("» " + m)
            continue
        if msg == "/say":
            import voice
            print("(recording 4s — speak now...)")
            text, vres = voice.listen_once()
            if not text:
                print(f"(mic: {vres.get('error')}) — type instead.")
                continue
            print(f"(heard: {text} | tone: {vres.get('label')} {vres.get('trust_delta', 0):+d} trust)")
            reply, action = npc.talk(text, "", voice=vres)
            tag = " (offline)" if npc.last_offline else ""
            print(f"Gruff{tag}: {reply}")
            continue
        reply, action = npc.talk(msg, "")
        tag = " (offline)" if npc.last_offline else ""
        print(f"Gruff{tag}: {reply}")


if __name__ == "__main__":
    main()

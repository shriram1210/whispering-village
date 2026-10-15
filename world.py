"""world.py - game rules and state.
Key idea: the LLM only SUGGESTS an action. These rules decide if it really happens,
so the game stays fair and predictable even if the AI misbehaves."""

COLS, ROWS, TILE = 30, 16, 32
FENCE_X, GATE_Y = 20, 8          # fence column splits village (left) from Old Forest (right)
ORE_POS = (26, 8)
TREES = [(12, 12), (13, 12), (3, 12), (1, 5), (24, 4), (26, 11), (25, 12), (23, 3), (27, 5), (22, 10), (28, 2)]
HOUSES = [("smithy", 3, 2, 4, 2), ("stall", 9, 9, 3, 2)]   # kind, tile x, tile y, width, height
POND = [(14, 2), (15, 2), (16, 2), (14, 3), (15, 3), (16, 3), (17, 3), (15, 4), (16, 4)]

# ---- tune these during testing ----
QUEST_TRUST = 20      # Gruff gives the quest at this trust or higher
GATE_TRUST = 15       # Rex opens the gate at this trust or higher
BAN_TRUST = -30       # Rex slams the gate shut at or below this
TASK_TRUST_MIRA = 10  # Mira hands out her moonpetal errand at this trust or higher
TASK_TRUST_REX = 10   # Rex assigns brazier patrol at this trust or higher
POTION_BASE = 20
START_GOLD = 50
FLOWER_SPOTS = [(12, 5), (17, 6), (5, 9)]      # moonpetals (walkable grass)
POSTS = [(18, 5), (18, 11), (10, 13)]          # watch braziers (west of the fence)


def build_map():
    grid = [["." for _ in range(COLS)] for _ in range(ROWS)]
    for x in range(COLS):
        grid[0][x] = grid[ROWS - 1][x] = "#"
    for y in range(ROWS):
        grid[y][0] = grid[y][COLS - 1] = "#"
        grid[y][FENCE_X] = "#"
    grid[GATE_Y][FENCE_X] = "G"
    for x, y in TREES:
        grid[y][x] = "T"
    for _, hx, hy, hw, hh in HOUSES:
        for yy in range(hy, hy + hh):
            for xx in range(hx, hx + hw):
                grid[yy][xx] = "H"
    for x, y in POND:
        grid[y][x] = "W"
    return grid


class World:
    def __init__(self, npcs):
        self.npcs = npcs
        self.grid = build_map()
        self.gold = START_GOLD
        self.inventory = []
        self.quest = "not_started"   # not_started -> active -> ore_found -> complete
        self.gate_open = False
        self.won = False
        self.day = 1                 # Stage 3: each Sleep runs one gossip night
        self.rumor_edges = {}        # (speaker, listener) -> day last gossiped
        self.mira_task = "not_started"  # Mira's errand: not_started -> active -> complete
        self.rex_task = "not_started"   # Rex's patrol: not_started -> active -> complete
        self.petals_found = set()    # flower spots already picked
        self.posts_lit = set()       # braziers already lit

    def advance_day(self):
        """Sleep: all NPCs condense today's turns into durable facts + daily summary."""
        from llm import ask_json
        self.day += 1
        msgs = [f"Day {self.day} dawns over the village."]
        for npc in self.npcs.values():
            npc.game_day = self.day
            try:
                s = npc.store.summarize_npc(npc, npc.history, ask_json, self.day) if npc.store else None
                msgs.append(f"{npc.name} dreamed: {s[:120]}" if s else f"{npc.name} slept dreamlessly (AI offline, retry tonight).")
            except Exception:
                msgs.append(f"{npc.name} slept dreamlessly.")
        return msgs

    # ---------- map ----------
    def is_solid(self, tx, ty):
        if not (0 <= tx < COLS and 0 <= ty < ROWS):
            return True
        t = self.grid[ty][tx]
        return t in "#THW" or (t == "G" and not self.gate_open)

    # ---------- consequences driven by trust ----------
    def potion_price(self):
        t = self.npcs["Mira"].trust
        if t >= 40:
            return round(POTION_BASE * 0.7)    # friends get 30% off
        if t <= -30:
            return round(POTION_BASE * 1.5)    # enemies pay 50% more
        return POTION_BASE

    def petal_count(self):
        return self.inventory.count("Moonpetal")

    def objective(self):
        bits = []
        bits.append({"not_started": "Earn Gruff's trust",
                     "active": "Fetch Iron Ore→Gruff",
                     "ore_found": "Bring Ore→Gruff",
                     "complete": "Main quest done ✓"}[self.quest])
        if self.mira_task == "active":
            bits.append(f"Moonpetals {self.petal_count()}/3→Mira")
        elif self.mira_task == "not_started":
            bits.append("Mira may have an errand")
        else:
            bits.append("Mira's errand done ✓")
        if self.rex_task == "active":
            bits.append(f"Braziers {len(self.posts_lit)}/3→Rex")
        elif self.rex_task == "not_started":
            bits.append("Rex may have patrol work")
        else:
            bits.append("Rex's patrol done ✓")
        return " · ".join(bits)

    # ---------- context given to the LLM so replies match the real game state ----------
    def context(self, name):
        if name == "Gruff":
            return (f"- Quest 'Iron Ore from the Old Forest' status: {self.quest}.\n"
                    f"- Player has Iron Ore: {'Iron Ore' in self.inventory}.\n"
                    f"- Use give_quest ONLY if quest status is not_started AND your trust is at least {QUEST_TRUST}.\n"
                    f"- Use complete_quest ONLY if the player has the Iron Ore.")
        if name == "Rex":
            return (f"- The gate is currently {'OPEN' if self.gate_open else 'LOCKED'}.\n"
                    f"- Patrol task status: {self.rex_task}. Braziers lit: {len(self.posts_lit)}/3.\n"
                    f"- Use open_gate ONLY if your trust is at least {GATE_TRUST} and the player seems honest and polite.\n"
                    f"- Use give_task_rex ONLY if patrol status is not_started AND your trust is at least {TASK_TRUST_REX}.\n"
                    f"- Use complete_task_rex ONLY if all 3 braziers are lit.\n"
                    f"- If your trust is very low you refuse and may threaten the player.")
        if name == "Mira":
            return (f"- A Healing Potion costs {self.potion_price()} gold for this player (base price {POTION_BASE}).\n"
                    f"- The player has {self.gold} gold and {self.petal_count()} Moonpetals.\n"
                    f"- Errand status: {self.mira_task}.\n"
                    f"- Use sell_potion ONLY when the player clearly agrees to buy one.\n"
                    f"- Use give_task_mira ONLY if errand status is not_started AND your trust is at least {TASK_TRUST_MIRA}.\n"
                    f"- Use complete_task_mira ONLY if the player has 3 Moonpetals.")
        return ""

    # ---------- apply an action suggested by the NPC ----------
    def apply(self, name, action):
        msgs = []
        npc = self.npcs[name]
        if action in (None, "none"):
            return msgs

        if action == "give_quest" and name == "Gruff" and self.quest == "not_started":
            if npc.trust >= QUEST_TRUST:
                self.quest = "active"
                msgs.append("New quest: fetch Iron Ore from the Old Forest (past Rex's gate).")
            else:
                msgs.append(f"Gruff doesn't trust you enough yet (needs {QUEST_TRUST}, has {npc.trust}).")

        elif action == "complete_quest" and name == "Gruff":
            if self.quest == "ore_found" and "Iron Ore" in self.inventory:
                self.inventory.remove("Iron Ore")
                self.inventory.append("Iron Sword")
                self.gold += 30
                npc.trust = min(100, npc.trust + 10)
                self.quest = "complete"
                self.won = True
                msgs.append("Quest complete! +30 gold and an Iron Sword.")
            else:
                msgs.append("You don't have the Iron Ore yet.")

        elif action == "open_gate" and name == "Rex":
            if npc.trust >= GATE_TRUST:
                if not self.gate_open:
                    self.gate_open = True
                    msgs.append("Rex unlocks the gate. The Old Forest is open.")
            else:
                msgs.append(f"Rex doesn't trust you enough yet (needs {GATE_TRUST}, has {npc.trust}).")

        elif action == "sell_potion" and name == "Mira":
            price = self.potion_price()
            if self.gold >= price:
                self.gold -= price
                self.inventory.append("Healing Potion")
                msgs.append(f"Bought a Healing Potion for {price} gold.")
            else:
                msgs.append(f"Not enough gold (a potion costs {price}).")

        elif action == "give_task_mira" and name == "Mira" and self.mira_task == "not_started":
            if npc.trust >= TASK_TRUST_MIRA:
                self.mira_task = "active"
                msgs.append("New errand: pick 3 Moonpetals (glowing flowers) and bring them to Mira.")
            else:
                msgs.append(f"Mira doesn't trust you enough yet (needs {TASK_TRUST_MIRA}, has {npc.trust}).")

        elif action == "complete_task_mira" and name == "Mira":
            if self.mira_task == "active" and self.petal_count() >= 3:
                for _ in range(3):
                    self.inventory.remove("Moonpetal")
                self.gold += 25
                npc.trust = min(100, npc.trust + 15)
                self.mira_task = "complete"
                msgs.append("Errand complete! +25 gold, Mira trusts you (+15).")
            else:
                msgs.append(f"You need 3 Moonpetals (have {self.petal_count()}).")

        elif action == "give_task_rex" and name == "Rex" and self.rex_task == "not_started":
            if npc.trust >= TASK_TRUST_REX:
                self.rex_task = "active"
                msgs.append("New patrol: light the 3 watch braziers, then report to Rex.")
            else:
                msgs.append(f"Rex doesn't trust you enough yet (needs {TASK_TRUST_REX}, has {npc.trust}).")

        elif action == "complete_task_rex" and name == "Rex":
            if self.rex_task == "active" and len(self.posts_lit) >= 3:
                self.gold += 20
                npc.trust = min(100, npc.trust + 15)
                self.rex_task = "complete"
                msgs.append("Patrol complete! +20 gold, Rex trusts you (+15).")
            else:
                msgs.append(f"Braziers lit: {len(self.posts_lit)}/3. Finish the patrol first.")
        return msgs

    def enforce_rules(self):
        """Run after every conversation: trust changes can reverse earlier decisions."""
        msgs = []
        if self.gate_open and self.npcs["Rex"].trust <= BAN_TRUST:
            self.gate_open = False
            msgs.append("Rex is furious and slams the gate shut!")
        return msgs

    def pickup_ore(self):
        if self.quest == "active":
            self.quest = "ore_found"
            self.inventory.append("Iron Ore")
            return ["You picked up the Iron Ore! Take it back to Gruff."]
        return []

    def pickup_petal(self, spot):
        if self.mira_task == "active" and spot not in self.petals_found:
            self.petals_found.add(spot)
            self.inventory.append("Moonpetal")
            n = self.petal_count()
            if n >= 3:
                return ["Moonpetal 3/3! Bring them back to Mira."]
            return [f"Picked a Moonpetal ({n}/3)."]
        return []

    def light_post(self, post):
        if self.rex_task == "active" and post not in self.posts_lit:
            self.posts_lit.add(post)
            n = len(self.posts_lit)
            if n >= 3:
                return ["All 3 braziers lit! Report back to Rex."]
            return [f"Brazier lit ({n}/3)."]
        return []

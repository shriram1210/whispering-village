"""main_web.py - Whispering Village (pygbag/WebAssembly build).
This version replaces threading with asyncio for pygbag compatibility.
Mic/voice features are disabled in web build (requires Web Audio API).
"""
import asyncio
import time
from collections import deque
import pygame
import llm
import gossip
from npc import load_npcs
from world import World, TILE, GATE_Y, FENCE_X, ORE_POS, FLOWER_SPOTS, POSTS
from art import Renderer, W, H, MAP_H, bright, YELLOW, WHITE, GREY, RED

TALK_DIST = 56


class Pending:
    """Runs the (slow) AI call as an asyncio task so the game never freezes."""
    def __init__(self, name, coro):
        self.name = name
        self.result = None
        self.done = False
        self.t0 = time.time()
        self._task = asyncio.create_task(self._run(coro))

    async def _run(self, coro):
        try:
            self.result = await coro
        except Exception as e:
            self.result = (f"(error: {e})", "none")
        self.done = True


def find_path(world, blocked, start, goals):
    """Breadth-first search over free tiles. Returns a list of tiles from start to the nearest goal."""
    q, prev = deque([start]), {start: None}
    while q:
        cur = q.popleft()
        if cur in goals:
            path = []
            while cur:
                path.append(cur)
                cur = prev[cur]
            return path[::-1]
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            n = (cur[0] + dx, cur[1] + dy)
            if n in prev or world.is_solid(*n) or n in blocked:
                continue
            prev[n] = cur
            q.append(n)
    return None


async def main():
    pygame.init()
    screen = pygame.display.set_mode((W, H))
    pygame.display.set_caption("Whispering Village")
    clock = pygame.time.Clock()

    npcs = load_npcs()
    rels = gossip.load_relationships()
    world = World(npcs)
    renderer = Renderer(world, npcs)
    npc_rects = {k: pygame.Rect(v.pos[0] * TILE + 4, v.pos[1] * TILE + 4, TILE - 8, TILE - 8)
                 for k, v in npcs.items()}
    npc_tiles = {tuple(v.pos) for v in npcs.values()}
    player = pygame.Rect(3 * TILE + 6, GATE_Y * TILE + 6, TILE - 12, TILE - 12)
    ore_rect = pygame.Rect(ORE_POS[0] * TILE + 6, ORE_POS[1] * TILE + 6, TILE - 12, TILE - 12)
    flower_rects = {s: pygame.Rect(s[0] * TILE + 6, s[1] * TILE + 6, TILE - 12, TILE - 12)
                    for s in FLOWER_SPOTS}
    post_rects = {p: pygame.Rect(p[0] * TILE + 6, p[1] * TILE + 6, TILE - 12, TILE - 12)
                  for p in POSTS}
    gate_rect = pygame.Rect(FENCE_X * TILE, GATE_Y * TILE, TILE, TILE)

    feed = [("Welcome! Click the ground to walk, click a villager to talk (or WASD + E). Earn trust, get a quest.", YELLOW)]
    state, active, text, pending = "walk", None, "", None
    map_open, selected_node, night_job = False, None, None
    moving, facing_left = False, False
    path, talk_after, stuck = [], None, 0
    ai_status, offline_warned, cursor_hand = "ready", False, False

    def collides(rect):
        for cx, cy in ((rect.left, rect.top), (rect.right - 1, rect.top),
                       (rect.left, rect.bottom - 1), (rect.right - 1, rect.bottom - 1)):
            if world.is_solid(cx // TILE, cy // TILE):
                return True
        return any(rect.colliderect(r) for r in npc_rects.values())

    def try_move(dx, dy):
        player.x += dx
        if collides(player):
            player.x -= dx
        player.y += dy
        if collides(player):
            player.y -= dy

    def npc_at(mx, my):
        for name, r in npc_rects.items():
            if pygame.Rect(r.centerx - 22, r.y - 26, 44, r.h + 50).collidepoint(mx, my):
                return name
        return None

    def is_near(name):
        r = npc_rects[name]
        return abs(r.centerx - player.centerx) < TALK_DIST and abs(r.centery - player.centery) < TALK_DIST

    def start_chat(name):
        nonlocal state, active, text, talk_after
        state, active, text, talk_after = "chat", name, "", None
        path.clear()
        feed.append((f"-- You approach {name}. Type and press Enter (or click Send). --", GREY))

    def leave_chat():
        nonlocal state, active
        state, active = "walk", None

    async def send_message():
        nonlocal text, pending
        msg = text.strip()
        if not msg or pending is not None:
            return
        npc, name = npcs[active], active
        feed.append((f"You: {msg}", WHITE))
        ctx = world.context(name)
        pending = Pending(name, npc.talk(msg, ctx))
        text = ""

    def start_night():
        nonlocal night_job, map_open
        if night_job is not None or state != "walk":
            return
        feed.append(("-- Night falls over the village... --", GREY))
        night_job = Pending("night", gossip.run_night(npcs, rels, world))
        map_open = True

    def walk_to(goals, then_talk=None):
        nonlocal talk_after
        start = (player.centerx // TILE, player.centery // TILE)
        p = find_path(world, npc_tiles, start, goals)
        if p is None:
            feed.append(("» You can't get there.", YELLOW))
            return
        path[:] = p
        talk_after = then_talk

    running = True
    while running:
        near = next((n for n in npc_rects if is_near(n)), None)

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                mx, my = event.pos
                if state == "walk" and renderer.sleep_rect and renderer.sleep_rect.collidepoint(mx, my):
                    start_night()
                elif map_open and state == "walk" and my < MAP_H:
                    pick = None
                    for i, name in enumerate(npcs):
                        x, y = Renderer.map_node_pos(i, len(npcs))
                        if (mx - x) ** 2 + (my - y) ** 2 <= 42 ** 2:
                            pick = name
                    selected_node = pick
                elif state == "walk" and my < MAP_H:
                    hit = npc_at(mx, my)
                    if hit and is_near(hit):
                        start_chat(hit)
                    elif hit:
                        nx, ny = npcs[hit].pos
                        goals = {(nx + dx, ny + dy) for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))
                                 if not world.is_solid(nx + dx, ny + dy) and (nx + dx, ny + dy) not in npc_tiles}
                        walk_to(goals, hit)
                    else:
                        tile = (mx // TILE, my // TILE)
                        if world.is_solid(*tile):
                            feed.append(("» You can't walk there." + (" The gate is locked." if tile == (FENCE_X, GATE_Y) else ""), YELLOW))
                        else:
                            walk_to({tile})
                elif state == "chat":
                    if renderer.send_rect and renderer.send_rect.collidepoint(event.pos):
                        await send_message()
                    elif renderer.leave_rect and renderer.leave_rect.collidepoint(event.pos):
                        leave_chat()
            elif event.type == pygame.KEYDOWN:
                if state == "walk":
                    if event.key == pygame.K_e and near:
                        start_chat(near)
                    elif event.key == pygame.K_n:
                        start_night()
                    elif event.key == pygame.K_m:
                        map_open = not map_open
                    elif event.key == pygame.K_ESCAPE and map_open:
                        map_open = False
                else:
                    if event.key == pygame.K_ESCAPE:
                        leave_chat()
                    elif event.key == pygame.K_RETURN:
                        await send_message()
                    elif event.key == pygame.K_BACKSPACE:
                        text = text[:-1]
                    elif event.unicode and event.unicode.isprintable() and len(text) < 140:
                        text += event.unicode

        # ----- movement (keyboard, or following a clicked path) -----
        moving = False
        if state == "walk":
            k = pygame.key.get_pressed()
            dx = (k[pygame.K_d] or k[pygame.K_RIGHT]) - (k[pygame.K_a] or k[pygame.K_LEFT])
            dy = (k[pygame.K_s] or k[pygame.K_DOWN]) - (k[pygame.K_w] or k[pygame.K_UP])
            if dx or dy:
                path.clear()
                talk_after = None
                moving = True
                if dx:
                    facing_left = dx < 0
                try_move(dx * 3, dy * 3)
            elif path:
                gx, gy = path[0][0] * TILE + TILE // 2, path[0][1] * TILE + TILE // 2
                dx = max(-3, min(3, gx - player.centerx))
                dy = max(-3, min(3, gy - player.centery))
                before = player.topleft
                try_move(dx, dy)
                moving = True
                if dx:
                    facing_left = dx < 0
                stuck = stuck + 1 if player.topleft == before else 0
                if player.center == (gx, gy):
                    path.pop(0)
                if stuck > 30:
                    path.clear()
                    talk_after = None
                    stuck = 0
                if not path and talk_after:
                    if is_near(talk_after):
                        start_chat(talk_after)
                    talk_after = None
            if world.quest == "active" and player.colliderect(ore_rect):
                for m in world.pickup_ore():
                    feed.append(("» " + m, YELLOW))
            for spot, fr in flower_rects.items():
                if player.colliderect(fr):
                    for m in world.pickup_petal(spot):
                        feed.append(("» " + m, YELLOW))
            for post, pr in post_rects.items():
                if player.colliderect(pr):
                    for m in world.light_post(post):
                        feed.append(("» " + m, YELLOW))

        # ----- AI reply arrived (or took too long) -----
        if pending and not pending.done and time.time() - pending.t0 > 35:
            feed.append((f"{pending.name} seems lost in thought. (The AI took too long. Try again.)", RED))
            pending = None
        if pending and pending.done:
            name = pending.name
            reply, action = pending.result
            feed.append((f"{name}: {reply}", bright(npcs[name].color)))
            if npcs[name].last_offline:
                ai_status = "offline"
                if not offline_warned:
                    why = (llm.last_error or "unknown reason")[:110]
                    feed.append((f"» AI is offline ({why}). Using built-in replies.", RED))
                    offline_warned = True
            else:
                ai_status, offline_warned = "online", False
            for m in world.apply(name, action) + world.enforce_rules():
                feed.append(("» " + m, YELLOW))
            if not world.gate_open and player.colliderect(gate_rect):
                player.x = (FENCE_X - 1) * TILE + 6
            pending = None

        # ----- gossip night finished -----
        if night_job and night_job.done:
            res = night_job.result
            night_job = None
            msgs = res.get("msgs", ["The night passes quietly."]) if isinstance(res, dict) else ["The night passes quietly."]
            for m in msgs:
                feed.append((m, YELLOW))

        # ----- hover cursor + draw -----
        mx, my = pygame.mouse.get_pos()
        hover = npc_at(mx, my) if (state == "walk" and my < MAP_H) else None
        want_hand = hover is not None
        if want_hand != cursor_hand:
            cursor_hand = want_hand
            try:
                pygame.mouse.set_cursor(pygame.SYSTEM_CURSOR_HAND if want_hand else pygame.SYSTEM_CURSOR_ARROW)
            except Exception:
                pass

        dest = (path[-1][0] * TILE + TILE // 2, path[-1][1] * TILE + TILE // 2) if path and state == "walk" else None
        renderer.draw_scene(screen, player, npc_rects, ore_rect, (near or hover) if state == "walk" else None,
                            moving, facing_left, dest)
        renderer.draw_panel(screen, state, active, feed, text, pending is not None, ai_status,
                            recording=False)
        if map_open and state == "walk":
            renderer.draw_rumor_map(screen, npcs, world.rumor_edges, world.day, selected_node)
        if world.won:
            renderer.draw_banner(screen, "QUEST COMPLETE!")
        pygame.display.flip()
        await asyncio.sleep(0)  # yield to event loop for pygbag
        clock.tick(60)

    pygame.quit()


if __name__ == "__main__":
    asyncio.run(main())
"""art.py - procedural pixel-art look for Whispering Village (no image files needed).
Twilight village: pixel characters, houses, pond, lantern glow, fireflies, RPG-style UI."""
import math
import os
import random
import pygame
from world import COLS, ROWS, TILE, FENCE_X, GATE_Y, HOUSES, POND
from world import FLOWER_SPOTS, POSTS, TASK_TRUST_MIRA, TASK_TRUST_REX
from npc import tier as trust_tier  # relationship tiers on the rumor map

PANEL_H = 210
MAP_H = ROWS * TILE
PANEL_Y = MAP_H
W, H = COLS * TILE, MAP_H + PANEL_H

# ---------- palette ----------
WHITE, GREY, GREY_L = (240, 240, 245), (140, 144, 165), (190, 194, 215)
YELLOW, GOLD = (255, 220, 110), (214, 168, 64)
RED, GREEN = (240, 100, 100), (110, 225, 130)
PANEL_BG, BOX_BG = (20, 22, 36), (36, 40, 62)
GRASS, FOREST, DIRT = (92, 150, 70), (46, 98, 60), (150, 118, 80)
STONE, WOOD, WOOD_DARK = (105, 108, 118), (128, 90, 52), (84, 56, 32)
WATER, WATER_HI, SAND = (44, 98, 165), (120, 175, 230), (200, 180, 120)
FLOWERS = [(245, 240, 130), (240, 120, 165), (250, 250, 250), (170, 140, 240)]
PATH_TILES = ({(x, 8) for x in range(1, 27)} | {(6, y) for y in range(6, 9)} |
              {(8, y) for y in range(8, 12)} | {(x, 11) for x in range(8, 12)})

FONT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "font.ttf")


def bright(c):
    return tuple(min(255, v + 80) for v in c)


def _shade(c, d):
    return tuple(max(0, min(255, v + d)) for v in c)


def wrap(text, font, width):
    lines, cur = [], ""
    for word in text.split(" "):
        test = (cur + " " + word).strip()
        if font.size(test)[0] <= width:
            cur = test
        else:
            if cur:
                lines.append(cur)
            cur = word
    lines.append(cur)
    return lines


def load_fonts():
    def f(size, bold=False):
        if os.path.exists(FONT_PATH):          # optional: drop a pixel font at assets/font.ttf
            return pygame.font.Font(FONT_PATH, size)
        return pygame.font.SysFont("trebuchetms,verdana,segoeui,arial", size, bold=bold)
    return {"body": f(19, True), "small": f(15), "label": f(14, True), "big": f(46, True), "marker": f(30, True)}


# ---------- characters (16x16 pixel template, scaled 2x) ----------
TEMPLATE = [
    "................",
    ".....OOOOOO.....",
    "....OHHHHHHO....",
    "....OHHHHHHO....",
    "....OHSSSSHO....",
    "....OSESSESO....",
    "....OSSSSSSO....",
    ".....OSSSSO.....",
    "....OOTTTTOO....",
    "...OTTTTTTTTO...",
    "...OTTTTTTTTO...",
    "...OSTTTTTTSO...",
    "....OPPPPPPO....",
    "....OPPOOPPO....",
    "....OBBO.OBBO...",
    "................",
]
_BASE = dict(O=(22, 20, 32), E=(20, 20, 30))
PALETTES = {
    "Player": dict(H=(90, 60, 40), S=(240, 200, 160), T=(60, 170, 210), P=(60, 60, 120), B=(70, 45, 30)),
    "Gruff": dict(H=(80, 50, 30), S=(225, 175, 135), T=(120, 76, 44), P=(70, 60, 60), B=(40, 30, 25)),
    "Mira": dict(H=(140, 50, 40), S=(235, 190, 150), T=(180, 70, 170), P=(130, 40, 130), B=(60, 30, 50)),
    "Rex": dict(H=(150, 155, 170), S=(225, 180, 140), T=(60, 90, 180), P=(50, 60, 90), B=(30, 30, 40),
                R=(210, 50, 50)),
}
EXTRAS = {   # extra pixels: (x, y, palette key)
    "Gruff": [(x, 6, "H") for x in range(5, 11)] + [(x, 7, "H") for x in range(6, 10)],   # beard
    "Mira": [(3, y, "H") for y in range(4, 9)] + [(12, y, "H") for y in range(4, 9)],      # long hair
    "Rex": [(7, 0, "R"), (8, 0, "R")],                                                      # helmet plume
}


def make_sprite(pal, extras=()):
    pal = {**_BASE, **pal}
    surf = pygame.Surface((16, 16), pygame.SRCALPHA)
    for y, row in enumerate(TEMPLATE):
        for x, ch in enumerate(row):
            if ch in pal:
                surf.set_at((x, y), pal[ch])
    for x, y, key in extras:
        surf.set_at((x, y), pal[key])
    return pygame.transform.scale(surf, (32, 32))


def make_sprites(npcs):
    sprites = {"Player": _baked("Player") or make_sprite(PALETTES["Player"])}
    for name, n in npcs.items():
        baked = _baked(name)
        if baked is not None:
            sprites[name] = baked
            continue
        pal = PALETTES.get(name) or dict(H=(90, 60, 40), S=(230, 190, 150), T=n.color,
                                         P=(70, 70, 90), B=(40, 30, 25))
        sprites[name] = make_sprite(pal, EXTRAS.get(name, ()))
    return sprites


def _baked(name):
    """Unity batchmode-rendered sprite (assets/sprites/<name>.png, magenta key).
    Returns None when missing so the procedural sprite is used."""
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "sprites", name + ".png")
    if not os.path.exists(p):
        return None
    try:
        img = pygame.image.load(p).convert()
        img.set_colorkey((255, 0, 255))
        return pygame.transform.scale(img, (32, 32))
    except Exception:
        return None


# ---------- static background (drawn once) ----------
def _draw_stone(bg, px, py, rng):
    c = _shade(STONE, rng.choice((-8, 0, 8)))
    bg.fill(c, (px, py, TILE, TILE))
    bg.fill(_shade(c, 24), (px, py, TILE, 3))
    bg.fill(_shade(c, 24), (px, py, 3, TILE))
    bg.fill(_shade(c, -32), (px, py + TILE - 3, TILE, 3))
    bg.fill(_shade(c, -32), (px + TILE - 3, py, 3, TILE))
    for _ in range(3):
        bg.fill(_shade(c, rng.choice((-18, 16))), (px + rng.randrange(4, 26), py + rng.randrange(4, 26), 3, 2))


def _draw_fence(bg, px, py):
    for ry in (py + 7, py + 20):
        bg.fill(WOOD, (px + 1, ry, TILE - 2, 5))
        bg.fill(_shade(WOOD, -30), (px + 1, ry + 4, TILE - 2, 1))
    bg.fill(WOOD, (px + 11, py, 10, TILE))
    bg.fill(WOOD_DARK, (px + 17, py, 4, TILE))
    bg.fill(_shade(WOOD, 25), (px + 11, py, 2, TILE))


def _draw_lantern(bg, cx, cy):
    bg.fill((50, 34, 20), (cx - 5, cy - 8, 10, 3))
    bg.fill((255, 170, 60), (cx - 4, cy - 5, 8, 10))
    bg.fill((255, 236, 150), (cx - 2, cy - 3, 4, 6))


def _draw_pond(bg):
    pond = set(POND)
    for x, y in pond:
        bg.fill(WATER, (x * TILE, y * TILE, TILE, TILE))
    for x, y in pond:
        px, py = x * TILE, y * TILE
        if (x, y - 1) not in pond:
            bg.fill(SAND, (px, py, TILE, 4))
        if (x, y + 1) not in pond:
            bg.fill(SAND, (px, py + TILE - 4, TILE, 4))
        if (x - 1, y) not in pond:
            bg.fill(SAND, (px, py, 4, TILE))
        if (x + 1, y) not in pond:
            bg.fill(SAND, (px + TILE - 4, py, 4, TILE))


def _draw_tree(bg, px, py):
    sh = pygame.Surface((28, 10), pygame.SRCALPHA)
    pygame.draw.ellipse(sh, (0, 0, 0, 80), sh.get_rect())
    bg.blit(sh, (px + 2, py + 24))
    bg.fill((96, 64, 36), (px + 12, py + 14, 8, 16))
    bg.fill((70, 46, 26), (px + 16, py + 14, 4, 16))
    for dx, dy, w, h, c in ((2, 0, 28, 16, (30, 84, 44)), (5, -8, 22, 12, (38, 102, 52)), (9, -14, 14, 10, (52, 124, 64))):
        bg.fill(c, (px + dx, py + dy, w, h))
        bg.fill(_shade(c, 28), (px + dx + 2, py + dy + 2, 5, 3))
    bg.fill((20, 50, 30), (px + 4, py + 22, 24, 4))  # dark under-rim: canopy depth
    for bx, by in ((6, 2), (20, 4), (13, -6)):
        bg.fill((95, 165, 95), (px + bx, py + by, 4, 3))  # moonlit leaf glints


def _draw_building(bg, kind, x, y, w, h):
    px, py, pw = x * TILE, y * TILE, w * TILE
    wy = py + TILE
    if kind == "smithy":
        bg.fill((172, 142, 102), (px, wy, pw, TILE))
        bg.fill((108, 100, 96), (px, wy + TILE - 8, pw, 8))
        for bx in list(range(px, px + pw, TILE)) + [px + pw - 4]:
            bg.fill(WOOD_DARK, (bx, wy, 4, TILE))
        bg.fill(WOOD_DARK, (px, wy + TILE // 2, pw, 3))  # mid timber beam
        # pitched gable roof: stepped rows + ridge cap + eave shadow
        for i in range(5):
            y0, inset = py - 22 + i * 6, i * 7
            bg.fill((152, 64, 54), (px - 6 + inset, y0, pw + 12 - inset * 2, 6))
            bg.fill((112, 44, 40), (px - 6 + inset, y0 + 4, pw + 12 - inset * 2, 2))
        bg.fill((92, 34, 32), (px + pw // 2 - 4, py - 24, 8, 6))
        bg.fill((110, 46, 40), (px - 6, wy - 3, pw + 12, 4))
        bg.fill((95, 95, 105), (px + pw - 34, py - 20, 14, 20))
        bg.fill((60, 60, 70), (px + pw - 36, py - 22, 18, 4))
        bg.fill(WOOD_DARK, (px + pw // 2 - 9, wy + 6, 18, TILE - 6))
        bg.fill(YELLOW, (px + pw // 2 + 4, wy + 18, 3, 3))
        for wx in (px + 14, px + pw - 30):
            bg.fill((255, 205, 110), (wx, wy + 6, 16, 14))
            bg.fill(WOOD_DARK, (wx + 7, wy + 6, 2, 14))
            bg.fill(WOOD_DARK, (wx, wy + 12, 16, 2))
    else:  # market stall
        bg.fill(WOOD_DARK, (px, py + 4, 4, TILE * 2 - 4))
        bg.fill(WOOD_DARK, (px + pw - 4, py + 4, 4, TILE * 2 - 4))
        bg.fill(WOOD, (px + 2, wy + 4, pw - 4, TILE - 6))
        bg.fill(WOOD_DARK, (px + 2, wy + TILE - 6, pw - 4, 3))
        for i, c in enumerate(((230, 70, 90), (90, 170, 240), (150, 230, 120), (230, 70, 90), (250, 200, 80))):
            bx = px + 12 + i * 16
            bg.fill(c, (bx, wy - 2, 7, 10))
            bg.fill(_shade(c, 60), (bx + 1, wy - 1, 2, 4))
            bg.fill((200, 180, 140), (bx + 2, wy - 5, 3, 3))
        for i in range(0, pw, 12):
            c = (214, 66, 66) if (i // 12) % 2 == 0 else (240, 236, 225)
            bg.fill(c, (px + i, py + 4, 12, 20))
            pygame.draw.circle(bg, c, (px + i + 6, py + 24), 6)


def _draw_cobble(bg, px, py, rng):
    bg.fill((110, 96, 78), (px, py, TILE, TILE))  # grout bed
    for _ in range(4):
        cx, cy = px + rng.randrange(2, 22), py + rng.randrange(2, 22)
        w, h = rng.randrange(7, 12), rng.randrange(6, 10)
        c = _shade((150, 142, 128), rng.choice((-10, 0, 10)))
        pygame.draw.ellipse(bg, c, (cx, cy, w, h))
        pygame.draw.ellipse(bg, _shade(c, 32), (cx + 1, cy + 1, w - 2, 3))  # moonlit top edge


def build_background(world):
    rng = random.Random(7)
    bg = pygame.Surface((COLS * TILE, MAP_H))
    for y in range(ROWS):
        for x in range(COLS):
            px, py = x * TILE, y * TILE
            on_path = (x, y) in PATH_TILES or world.grid[y][x] == "G"
            if on_path:
                _draw_cobble(bg, px, py, random.Random(x * 917 + y * 131))
                continue
            base = FOREST if x > FENCE_X else GRASS
            col = _shade(base, rng.choice((-6, -3, 0, 0, 4, 7)))
            bg.fill(col, (px, py, TILE, TILE))
            for _ in range(6):
                bg.fill(_shade(col, rng.choice((-16, 14))),
                        (px + rng.randrange(1, TILE - 3), py + rng.randrange(1, TILE - 3), 2, 2))
            if world.grid[y][x] == "." and rng.random() < 0.05:
                bg.fill(rng.choice(FLOWERS), (px + rng.randrange(4, 26), py + rng.randrange(4, 26), 3, 3))
            if base == GRASS and world.grid[y][x] == "." and rng.random() < 0.35:
                trng = random.Random(x * 557 + y * 313)  # stable tufts, not per-build noise
                for _ in range(3):
                    gx, gy = px + trng.randrange(4, 28), py + trng.randrange(18, 28)
                    bg.fill((120, 185, 95), (gx, gy, 2, 5))
                    bg.fill((140, 205, 110), (gx, gy, 1, 4))
    for y in range(ROWS):
        for x in range(COLS):
            if world.grid[y][x] == "#":
                if x == FENCE_X and 0 < y < ROWS - 1:
                    _draw_fence(bg, x * TILE, y * TILE)
                else:
                    _draw_stone(bg, x * TILE, y * TILE, rng)
    _draw_pond(bg)
    for kind, hx, hy, hw, hh in HOUSES:
        _draw_building(bg, kind, hx, hy, hw, hh)
    for y in range(ROWS):
        for x in range(COLS):
            if world.grid[y][x] == "T":
                _draw_tree(bg, x * TILE, y * TILE)
    for dy in (-1, 1):
        _draw_lantern(bg, FENCE_X * TILE + 16, (GATE_Y + dy) * TILE + 8)
    return bg


# ---------- lighting ----------
def make_glow(r, color):
    s = pygame.Surface((r * 2, r * 2))
    for i in range(r, 0, -2):
        k = (1 - i / r) ** 2
        pygame.draw.circle(s, tuple(int(c * k) for c in color), (r, r), i)
    return s


def make_overlay():
    ov = pygame.Surface((W, MAP_H), pygame.SRCALPHA)
    ov.fill((26, 20, 92, 64))                       # twilight tint
    small = pygame.Surface((64, 40), pygame.SRCALPHA)
    for y in range(40):
        for x in range(64):
            d = ((x - 32) / 32) ** 2 + ((y - 20) / 20) ** 2
            small.set_at((x, y), (0, 0, 20, max(0, min(120, int((d - 0.55) * 95)))))
    ov.blit(pygame.transform.smoothscale(small, (W, MAP_H)), (0, 0))
    return ov


class Fireflies:
    def __init__(self):
        rng = random.Random(3)
        self.f = [(rng.uniform((FENCE_X + 1) * TILE, (COLS - 1) * TILE), rng.uniform(TILE, (ROWS - 1) * TILE),
                   rng.uniform(0, 6.28), rng.uniform(0.6, 1.4)) for _ in range(16)]
        self.glow = make_glow(9, (130, 120, 40))

    def draw(self, screen, t):
        for x, y, ph, sp in self.f:
            px = x + 16 * math.sin(t / 1000 * sp + ph)
            py = y + 10 * math.cos(t / 1300 * sp + ph * 1.3)
            b = 0.5 + 0.5 * math.sin(t / 400 * sp + ph * 2)
            screen.blit(self.glow, (int(px) - 9, int(py) - 9), special_flags=pygame.BLEND_RGB_ADD)
            pygame.draw.circle(screen, (int(255 * b), int(240 * b), int(120 * b)), (int(px), int(py)), 2)


class Smoke:
    """Chimney smoke: 6 looping puffs rising with sway (sibling of Fireflies)."""

    def __init__(self, x, y):
        self.x, self.y = x, y

    def draw(self, screen, t):
        for i in range(6):
            ph = (t / 1600 + i / 6) % 1.0
            r = 3 + int(ph * 7)
            a = max(0, 110 - int(ph * 130))
            s = pygame.Surface((r * 2, r * 2), pygame.SRCALPHA)
            pygame.draw.circle(s, (150, 150, 170, a), (r, r), r)
            screen.blit(s, (int(self.x + 10 * math.sin(ph * 5 + i) - r),
                            int(self.y - ph * 46 - r)))


# ---------- renderer ----------
class Renderer:
    def __init__(self, world, npcs):
        self.world, self.npcs = world, npcs
        self.send_rect = self.leave_rect = self.sleep_rect = None  # clickable buttons (set when drawing the panel)
        self.fonts = load_fonts()
        self.sprites = make_sprites(npcs)
        self.portraits = {k: pygame.transform.scale(v, (64, 64)) for k, v in self.sprites.items()}
        self.bg = build_background(world)
        self.overlay = make_overlay()
        self.flies = Fireflies()
        self.smoke = None
        for kind, hx, hy, hw, hh in HOUSES:
            if kind == "smithy":
                self.smoke = Smoke(hx * TILE + hw * TILE - 27, hy * TILE - 22)
        self.shadow = pygame.Surface((24, 10), pygame.SRCALPHA)
        pygame.draw.ellipse(self.shadow, (0, 0, 0, 90), self.shadow.get_rect())
        self.glows = [make_glow(78, tuple(int(c * k) for c in (120, 78, 24))) for k in (0.85, 1.0, 0.92)]
        self.ore_glow = make_glow(44, (90, 70, 24))
        lights = [(FENCE_X * TILE + 16, (GATE_Y + d) * TILE + 8) for d in (-1, 1)]
        for kind, hx, hy, hw, hh in HOUSES:
            px, py, pw = hx * TILE, hy * TILE, hw * TILE
            if kind == "smithy":
                lights += [(px + 22, py + TILE + 13), (px + pw - 22, py + TILE + 13)]
            else:
                lights.append((px + pw // 2, py + TILE))
        self.lights = lights

    # ----- world -----
    def _plate(self, screen, text, cx, cy, color=WHITE):
        img = self.fonts["label"].render(text, True, color)
        r = img.get_rect(center=(cx, cy)).inflate(12, 4)
        pill = pygame.Surface(r.size, pygame.SRCALPHA)
        pygame.draw.rect(pill, (10, 10, 25, 175), pill.get_rect(), border_radius=7)
        screen.blit(pill, r.topleft)
        screen.blit(img, img.get_rect(center=r.center))

    def _gate(self, screen):
        px, py = FENCE_X * TILE, GATE_Y * TILE
        # forest arch: tall posts + beam + vines + hanging lantern (static dressing)
        for postx in (px - 9, px + TILE + 1):
            pygame.draw.rect(screen, WOOD_DARK, (postx, py - 28, 9, TILE + 28))
            pygame.draw.rect(screen, _shade(WOOD_DARK, 30), (postx, py - 28, 3, TILE + 28))
            for vy in range(py - 22, py + TILE, 9):
                pygame.draw.rect(screen, (46, 110, 58), (postx + 1, vy, 3, 6))  # vines
        pygame.draw.rect(screen, WOOD, (px - 12, py - 32, TILE + 26, 9))
        pygame.draw.rect(screen, _shade(WOOD, -30), (px - 12, py - 27, TILE + 26, 4))
        pygame.draw.rect(screen, (255, 190, 90), (px + TILE // 2 - 3, py - 22, 6, 9))  # hanging lantern
        pygame.draw.rect(screen, (50, 34, 20), (px + TILE // 2 - 3, py - 25, 6, 3))
        if self.world.gate_open:
            pygame.draw.rect(screen, WOOD_DARK, (px, py, 5, TILE))
            pygame.draw.rect(screen, WOOD_DARK, (px + TILE - 5, py, 5, TILE))
        else:
            pygame.draw.rect(screen, WOOD, (px, py, TILE, TILE))
            for bx in (px + 5, px + 14, px + 23):
                pygame.draw.rect(screen, WOOD_DARK, (bx, py + 2, 4, TILE - 4))
            for ry in (py + 8, py + 21):
                pygame.draw.rect(screen, (70, 72, 82), (px, ry, TILE, 4))
            pygame.draw.rect(screen, (30, 24, 16), (px, py, TILE, TILE), 2)

    def _water(self, screen, t):
        for i, (x, y) in enumerate(POND):
            ox = int(8 + 8 * math.sin(t / 500 + i))
            pygame.draw.rect(screen, WATER_HI, (x * TILE + ox, y * TILE + 12, 10, 2))
            ox = int(8 + 8 * math.cos(t / 620 + i * 1.7))
            pygame.draw.rect(screen, WATER_HI, (x * TILE + ox, y * TILE + 23, 8, 2))

    def _entity(self, screen, name, rect, bob=0, flip=False):
        depth = 0.92 + 0.16 * (rect.bottom / MAP_H)  # fake perspective: nearer = bigger
        w = max(24, int(32 * depth))
        h = max(24, int(32 * depth))
        spr = pygame.transform.scale(self.sprites[name], (w, h))
        if flip:
            spr = pygame.transform.flip(spr, True, False)
        screen.blit(self.shadow, (rect.centerx - 12, rect.bottom - 6))
        screen.blit(spr, (rect.centerx - w // 2, rect.bottom - h - bob))

    def _marker(self, name):
        q = self.world.quest
        if name == "Gruff" and q == "not_started":
            return "!"
        if name == "Gruff" and q == "ore_found":
            return "?"
        t = self.npcs[name].trust
        if name == "Mira":
            if self.world.mira_task == "not_started" and t >= TASK_TRUST_MIRA:
                return "!"
            if self.world.mira_task == "active" and self.world.petal_count() >= 3:
                return "?"
        if name == "Rex":
            if self.world.rex_task == "not_started" and t >= TASK_TRUST_REX:
                return "!"
            if self.world.rex_task == "active" and len(self.world.posts_lit) >= 3:
                return "?"
        return None

    def _draw_task_spots(self, screen, t):
        if self.world.mira_task == "active":
            for x, y in FLOWER_SPOTS:
                if (x, y) in self.world.petals_found:
                    continue
                cx, cy = x * TILE + 16, y * TILE + 16
                pulse = int(2 * math.sin(t / 300 + x))
                pygame.draw.circle(screen, (70, 200, 120), (cx, cy), 10 + pulse)
                pygame.draw.line(screen, (50, 140, 70), (cx, cy), (cx, cy + 10), 2)
                for dx, dy in ((0, -6), (5, -2), (-5, -2), (3, 4), (-3, 4)):
                    pygame.draw.circle(screen, (245, 200, 230), (cx + dx, cy + dy), 3)
                pygame.draw.circle(screen, (255, 235, 130), (cx, cy - 1), 3)
                self._plate(screen, "Moonpetal", cx, cy - 22, (180, 255, 190))
        if self.world.rex_task == "active":
            for x, y in POSTS:
                lit = (x, y) in self.world.posts_lit
                cx, cy = x * TILE + 16, y * TILE + 16
                pygame.draw.rect(screen, (95, 95, 105), (cx - 8, cy + 4, 16, 10))
                pygame.draw.ellipse(screen, (40, 38, 48), (cx - 10, cy - 4, 20, 10))
                if lit:
                    fl = int(3 * math.sin(t / 120 + x + y))
                    pygame.draw.ellipse(screen, (240, 120, 40), (cx - 5, cy - 16 + fl, 10, 14))
                    pygame.draw.ellipse(screen, (255, 220, 130), (cx - 3, cy - 12 + fl, 6, 8))
                self._plate(screen, "Brazier" if not lit else "Lit!", cx, cy - 24,
                            YELLOW if lit else GREY_L)

    def draw_scene(self, screen, player, npc_rects, ore_rect, near, moving, facing_left, dest=None):
        t = pygame.time.get_ticks()
        screen.blit(self.bg, (0, 0))
        self._gate(screen)
        self._water(screen, t)
        bob = int(abs(math.sin(t / 110)) * 3) if moving else 0
        ents = [(r.bottom, n) for n, r in npc_rects.items()] + [(player.bottom, "Player")]
        for _, name in sorted(ents):
            if name == "Player":
                self._entity(screen, "Player", player, bob, facing_left)
            else:
                self._entity(screen, name, npc_rects[name])

        if dest:
            pygame.draw.circle(screen, YELLOW, dest, 7 + int(2 * math.sin(t / 150)), 2)
        if self.smoke:
            self.smoke.draw(screen, t)
        screen.blit(self.overlay, (0, 0))
        for i, (lx, ly) in enumerate(self.lights):
            g = self.glows[(t // 160 + i) % 3]
            screen.blit(g, (lx - 78, ly - 78), special_flags=pygame.BLEND_RGB_ADD)
        self.flies.draw(screen, t)

        if self.world.quest == "active":
            c = ore_rect.move(0, int(math.sin(t / 300) * 2))
            screen.blit(self.ore_glow, (c.centerx - 44, c.centery - 44), special_flags=pygame.BLEND_RGB_ADD)
            pygame.draw.rect(screen, (120, 122, 134), c)
            for dx, dy in ((3, 3), (11, 7), (5, 12)):
                pygame.draw.rect(screen, (245, 195, 120), (c.x + dx, c.y + dy, 5, 5))
            pygame.draw.rect(screen, (30, 30, 40), c, 1)
            self._plate(screen, "Iron Ore", c.centerx, c.y - 14, YELLOW)

        self._draw_task_spots(screen, t)

        for name, r in npc_rects.items():
            self._plate(screen, name, r.centerx, r.y - 22, bright(self.npcs[name].color))
            m = self._marker(name)
            if m:
                img = self.fonts["marker"].render(m, True, YELLOW)
                screen.blit(img, img.get_rect(center=(r.centerx, r.y - 46 + int(math.sin(t / 250) * 3))))
            if near == name:
                self._plate(screen, "Click or press E to talk", r.centerx, r.bottom + 14, YELLOW)

    def draw_banner(self, screen, text):
        img = self.fonts["big"].render(text, True, YELLOW)
        r = img.get_rect(center=(W // 2, 52)).inflate(50, 22)
        pygame.draw.rect(screen, (20, 18, 34), r, border_radius=12)
        pygame.draw.rect(screen, GOLD, r, 3, border_radius=12)
        screen.blit(img, img.get_rect(center=r.center))

    # ----- UI panel -----
    def draw_panel(self, screen, state, active, feed, text, thinking, ai_status="ready", recording=False):
        f, s = self.fonts["body"], self.fonts["small"]
        w = self.world
        pygame.draw.rect(screen, PANEL_BG, (0, PANEL_Y, W, PANEL_H))
        pygame.draw.rect(screen, GOLD, (0, PANEL_Y, W, 3))

        pygame.draw.circle(screen, GOLD, (26, PANEL_Y + 24), 9)
        pygame.draw.circle(screen, (255, 238, 160), (26, PANEL_Y + 24), 4)
        screen.blit(f.render(str(w.gold), True, WHITE), (42, PANEL_Y + 13))
        screen.blit(s.render("Bag: " + (", ".join(w.inventory) or "empty"), True, GREY_L), (110, PANEL_Y + 16))
        chip = {"online": ("AI: online", GREEN), "offline": ("AI: offline", RED)}.get(ai_status, ("AI: ready", GREY))
        screen.blit(s.render(chip[0], True, chip[1]), (380, PANEL_Y + 16))

        if state == "chat":
            n = self.npcs[active]
            col = GREEN if n.trust >= 15 else RED if n.trust < 0 else WHITE
            bar = pygame.Rect(W - 170, PANEL_Y + 18, 150, 12)
            pygame.draw.rect(screen, (50, 52, 76), bar, border_radius=6)
            fw = int(abs(n.trust) / 100 * 75)
            fill = pygame.Rect(bar.centerx if n.trust >= 0 else bar.centerx - fw, bar.y, fw, bar.h)
            pygame.draw.rect(screen, col, fill)
            pygame.draw.line(screen, WHITE, (bar.centerx, bar.y - 2), (bar.centerx, bar.bottom + 2), 2)
            label = s.render(f"{active} | {n.mood} | trust {n.trust:+d}", True, col)
            screen.blit(label, (bar.x - label.get_width() - 12, PANEL_Y + 15))

        box = pygame.Rect(10, PANEL_Y + 42, W - 20, 26)
        pygame.draw.rect(screen, (54, 46, 26), box, border_radius=6)
        pygame.draw.rect(screen, GOLD, box, 1, border_radius=6)
        screen.blit(s.render("!", True, GOLD), (20, box.y + 4))
        screen.blit(s.render(w.objective(), True, YELLOW), (38, box.y + 5))

        x0 = 98 if state == "chat" else 16
        if state == "chat":
            frame = pygame.Rect(14, PANEL_Y + 78, 70, 70)
            pygame.draw.rect(screen, (14, 16, 26), frame, border_radius=8)
            pygame.draw.rect(screen, bright(self.npcs[active].color), frame, 2, border_radius=8)
            screen.blit(self.portraits[active], (frame.x + 3, frame.y + 3))
        rows = []
        for msg, color in feed[-12:]:
            for line in wrap(msg, s, W - x0 - 16):
                rows.append((line, color))
        for i, (line, color) in enumerate(rows[-5:]):
            screen.blit(s.render(line, True, color), (x0, PANEL_Y + 76 + i * 19))

        chat = state == "chat"
        inp = pygame.Rect(10, H - 36, W - 20 - (244 if chat else 0), 26)
        pygame.draw.rect(screen, BOX_BG, inp, border_radius=7)
        pygame.draw.rect(screen, GOLD if chat else (60, 64, 90), inp, 1, border_radius=7)
        if chat:
            if recording:
                pulse = (pygame.time.get_ticks() // 400) % 2 == 0
                shown, color = "Listening... speak now", (255, 120, 120) if pulse else GREY
            elif thinking:
                shown, color = f"{active} is thinking...", GREY
            else:
                caret = "|" if (pygame.time.get_ticks() // 500) % 2 == 0 else ""
                shown, color = "> " + text, WHITE
                while s.size(shown + caret)[0] > inp.w - 20:
                    shown = shown[1:]
                shown += caret
            self.send_rect = pygame.Rect(inp.right + 8, H - 36, 88, 26)
            self.leave_rect = pygame.Rect(self.send_rect.right + 8, H - 36, 96, 26)
            self.mic_rect = pygame.Rect(self.leave_rect.right + 8, H - 36, 36, 26)
            for rect, label, col in ((self.send_rect, "Send", (46, 116, 70)), (self.leave_rect, "Leave", (128, 58, 58))):
                pygame.draw.rect(screen, col, rect, border_radius=7)
                pygame.draw.rect(screen, WHITE, rect, 1, border_radius=7)
                img = s.render(label, True, WHITE)
                screen.blit(img, img.get_rect(center=rect.center))
            # mic button: slate normally, pulsing red while recording
            pulse = recording and (pygame.time.get_ticks() // 400) % 2 == 0
            pygame.draw.rect(screen, (150, 50, 50) if pulse else (58, 66, 110), self.mic_rect, border_radius=7)
            pygame.draw.rect(screen, WHITE, self.mic_rect, 1, border_radius=7)
            self._mic_glyph(screen, self.mic_rect.center)
            if recording:
                pygame.draw.circle(screen, (255, 60, 60),
                                   (self.mic_rect.centerx, self.mic_rect.centery - 22), 5)
        else:
            self.send_rect = self.leave_rect = self.mic_rect = None
            self.sleep_rect = pygame.Rect(W - 120, H - 36, 110, 26)
            pygame.draw.rect(screen, (58, 66, 110), self.sleep_rect, border_radius=7)
            pygame.draw.rect(screen, WHITE, self.sleep_rect, 1, border_radius=7)
            img = s.render("Sleep (N)", True, WHITE)
            screen.blit(img, img.get_rect(center=self.sleep_rect.center))
            shown, color = "Click ground to walk, villager to talk (E)   M: rumor map", GREY
        screen.blit(s.render(shown, True, color), (inp.x + 10, inp.y + 5))

    @staticmethod
    def _mic_glyph(screen, center):
        """Procedural microphone icon (no assets needed)."""
        cx, cy = center
        pygame.draw.rect(screen, (240, 240, 245), (cx - 4, cy - 8, 8, 12), border_radius=4)
        pygame.draw.arc(screen, (240, 240, 245), (cx - 7, cy - 4, 14, 12), 3.34, 6.09, 2)
        pygame.draw.line(screen, (240, 240, 245), (cx, cy + 7), (cx, cy + 10), 2)
        for i in range(3):
            pygame.draw.line(screen, (240, 240, 245), (cx - 3 + i * 3, cy - 5), (cx - 3 + i * 3, cy + 2), 1)

    @staticmethod
    def trust_color(trust):
        return GREEN if trust >= 15 else RED if trust < 0 else WHITE

    @staticmethod
    def map_node_pos(i, n):
        """Circle layout shared by drawing + click hit-testing."""
        import math as _m
        cx, cy, r = W // 2, MAP_H // 2 - 10, min(W, MAP_H) // 2 - 90
        a = -_m.pi / 2 + 2 * _m.pi * i / max(1, n)
        return (int(cx + r * _m.cos(a)), int(cy + r * _m.sin(a)))

    def draw_rumor_map(self, screen, npcs, edges, day, selected):
        s = self.fonts["small"]
        dim = pygame.Surface((W, MAP_H), pygame.SRCALPHA)
        dim.fill((8, 8, 20, 210))
        screen.blit(dim, (0, 0))
        title = self.fonts["body"].render(f"Rumor map — night {day}   (M/Esc: close, click a villager)",
                                          True, YELLOW)
        screen.blit(title, (W // 2 - title.get_width() // 2, 14))
        names = list(npcs)
        pos = {name: self.map_node_pos(i, len(names)) for i, name in enumerate(names)}
        for (a, b), d in edges.items():
            if a in pos and b in pos:
                age = max(0, day - d)
                col = (255, 220, 110) if age == 0 else (140, 140, 160)
                pygame.draw.line(screen, col, pos[a], pos[b], 4 if age == 0 else 2)
        for name in names:
            n = npcs[name]
            x, y = pos[name]
            col = self.trust_color(n.trust)
            pygame.draw.circle(screen, (10, 10, 25), (x, y), 34)
            pygame.draw.circle(screen, col, (x, y), 34, 3)
            screen.blit(self.portraits[name], (x - 32, y - 32))
            lbl = self.fonts["label"].render(f"{name} · {trust_tier(n.trust)} {n.trust:+d}", True, col)
            screen.blit(lbl, (x - lbl.get_width() // 2, y + 36))
            if name == selected:
                pygame.draw.circle(screen, YELLOW, (x, y), 42, 2)
                beliefs = (n.memories[-4:] if n.memories else ["(believes nothing yet)"])
                for i, bline in enumerate(beliefs):
                    for j, ln in enumerate(wrap("• " + bline, s, W - 60)):
                        screen.blit(s.render(ln, True, GREY_L),
                                    (30, MAP_H - 130 + i * 22 + j * 18))

"""memory.py - scalable per-NPC persistent memory (Generative-Agents-lite).

Design (never stuff full history into prompts):
- Short-term: NPC.history (last 8 turns, in-process only).
- Long-term (SQLite): episodic facts (FTS5) + daily summaries + rolling profile.
- Prompt gets: rolling profile + latest daily summary + top-k retrieved facts
  + recent buffer. 10,000 conversations cost the same as 10.

Patterns: Stanford Generative Agents (memory stream: recency+relevance+importance),
Mem0 (add/search per id). SQLite only, no server, no embeddings.
"""
import functools
import os
import sqlite3
import threading
import time

SUMMARY_EVERY_TURNS = 20   # auto-summarize one NPC after this many player turns
RETRIEVE_K = 4             # facts pulled into each prompt


def _locked(fn):
    """Serialize SQLite access: talk() runs in Pending background threads,
    so one shared connection must never be touched concurrently."""
    @functools.wraps(fn)
    def w(self, *a, **k):
        with self._lock:
            return fn(self, *a, **k)
    return w


def _db_path(path=None):
    if path:
        return path
    here = os.path.dirname(os.path.abspath(__file__))
    os.makedirs(os.path.join(here, "data"), exist_ok=True)
    return os.path.join(here, "data", "game_memory.db")


class MemoryStore:
    def __init__(self, path=None):
        self.path = _db_path(path)
        self.fts = True
        self._lock = threading.RLock()  # re-entrant: summarize_npc calls other locked methods
        # Game talk() runs in background threads: allow cross-thread use (lock guards it).
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._init()

    def _init(self):
        c = self._conn
        c.execute("""CREATE TABLE IF NOT EXISTS memories(
            id INTEGER PRIMARY KEY, npc_id TEXT, text TEXT,
            kind TEXT DEFAULT 'obs', importance REAL DEFAULT 5.0,
            created REAL, last_access REAL)""")
        try:
            c.execute("CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(text, content='memories', content_rowid='id')")
            c.execute("""CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
                INSERT INTO memories_fts(rowid, text) VALUES (new.id, new.text); END""")
        except sqlite3.OperationalError:
            self.fts = False  # SQLite without FTS5: fall back to LIKE search
        c.execute("""CREATE TABLE IF NOT EXISTS daily_summaries(
            id INTEGER PRIMARY KEY, npc_id TEXT, game_day INT, summary TEXT, created REAL)""")
        c.execute("""CREATE TABLE IF NOT EXISTS npc_profile(
            npc_id TEXT PRIMARY KEY, rolling_summary TEXT DEFAULT '', updated_at REAL)""")
        c.execute("""CREATE TABLE IF NOT EXISTS npc_state(
            npc_id TEXT PRIMARY KEY, game_day INT DEFAULT 1,
            turns INT DEFAULT 0, last_summary_turn INT DEFAULT 0)""")
        c.commit()

    # ---------- write ----------
    @_locked
    def add_fact(self, npc_id, text, importance=5.0, kind="obs"):
        text = (text or "").strip()
        if not text or text.lower() == "null":
            return None
        now = time.time()
        cur = self._conn.execute(
            "INSERT INTO memories(npc_id,text,kind,importance,created,last_access) VALUES(?,?,?,?,?,?)",
            (npc_id, text[:300], kind, float(importance), now, now))
        self._conn.commit()
        return cur.lastrowid

    @_locked
    def record_day(self, npc_id, game_day, summary):
        now = time.time()
        self._conn.execute("INSERT INTO daily_summaries(npc_id,game_day,summary,created) VALUES(?,?,?,?)",
                           (npc_id, game_day, summary[:800], now))
        cur = self._conn.execute("UPDATE npc_profile SET rolling_summary=?, updated_at=? WHERE npc_id=?",
                                 (summary[:800], now, npc_id))
        if cur.rowcount == 0:
            self._conn.execute("INSERT INTO npc_profile(npc_id,rolling_summary,updated_at) VALUES(?,?,?)",
                               (npc_id, summary[:800], now))
        self._conn.commit()

    @_locked
    def bump_turns(self, npc_id, game_day=1):
        self._conn.execute("INSERT OR IGNORE INTO npc_state(npc_id,game_day) VALUES(?,?)", (npc_id, game_day))
        self._conn.execute("UPDATE npc_state SET turns=turns+1 WHERE npc_id=?", (npc_id,))
        self._conn.commit()
        row = self._conn.execute("SELECT turns,last_summary_turn FROM npc_state WHERE npc_id=?", (npc_id,)).fetchone()
        return row[0] - row[1]  # turns since last summary

    @_locked
    def mark_summarized(self, npc_id, game_day=1):
        self._conn.execute("INSERT OR IGNORE INTO npc_state(npc_id,game_day) VALUES(?,?)", (npc_id, game_day))
        self._conn.execute("UPDATE npc_state SET last_summary_turn=turns, game_day=? WHERE npc_id=?", (game_day, npc_id))
        self._conn.commit()

    @_locked
    def fact_count(self, npc_id):
        return self._conn.execute("SELECT COUNT(*) FROM memories WHERE npc_id=?", (npc_id,)).fetchone()[0]

    # ---------- read ----------
    @_locked
    def retrieve(self, npc_id, query, k=RETRIEVE_K):
        """Top-k facts by relevance + importance + recency. Never raises."""
        try:
            words = [w.strip('.,!?"\'').lower() for w in (query or "").split()]
            words = [w for w in words if len(w) > 2][:8]
            rows = []
            if self.fts and words:
                q = " OR ".join(f'"{w}"' for w in words)
                rows = self._conn.execute(
                    """SELECT m.id,m.text,m.importance,m.created,m.last_access,rank
                       FROM memories_fts JOIN memories m ON m.id=memories_fts.rowid
                       WHERE memories_fts MATCH ? AND m.npc_id=? LIMIT 12""", (q, npc_id)).fetchall()
            if not rows:
                like = f"%{words[0]}%" if words else "%"
                rows = self._conn.execute(
                    "SELECT id,text,importance,created,last_access,0 FROM memories WHERE npc_id=? AND text LIKE ? LIMIT 12",
                    (npc_id, like)).fetchall()
            now = time.time()
            scored = []
            for rid, text, imp, created, accessed, rank in rows:
                recency = 0.995 ** max(0.0, (now - accessed) / 3600.0)
                scored.append((float(imp or 0) + 5.0 * recency - float(rank or 0), rid, text))
            scored.sort(reverse=True)
            ids = [r[1] for r in scored[:k]]
            if ids:
                self._conn.execute(f"UPDATE memories SET last_access=? WHERE id IN ({','.join('?'*len(ids))})",
                                   (now, *ids))
                self._conn.commit()
            return [r[2] for r in scored[:k]]
        except Exception:
            return []

    @_locked
    def latest_summary(self, npc_id):
        row = self._conn.execute("SELECT summary FROM daily_summaries WHERE npc_id=? ORDER BY game_day DESC LIMIT 1",
                                 (npc_id,)).fetchone()
        return row[0] if row else ""

    @_locked
    def rolling(self, npc_id):
        row = self._conn.execute("SELECT rolling_summary FROM npc_profile WHERE npc_id=?", (npc_id,)).fetchone()
        return row[0] if row and row[0] else ""

    # ---------- summarization (LLM in, facts out) ----------
    SUMMARY_SYSTEM = ("You are a memory clerk for a game NPC. Reply ONLY with JSON: "
                      '{"facts":[{"text":"...","importance":1-10}],"daily_summary":"..."}')

    @_locked
    def summarize_npc(self, npc, turns, llm_fn, game_day=1):
        """Condense recent turns -> durable facts + daily paragraph. Returns summary or None (deferred)."""
        if not turns:
            return None
        convo = "\n".join(turns[-20:])
        try:
            data = llm_fn(self.SUMMARY_SYSTEM,
                          f"Summarize what {npc.name} learned about the player. Keep 1-5 durable facts "
                          f"(names, promises, deeds, preferences) with importance 1-10; drop trivia.\n{convo}")
        except Exception:
            return None
        if not isinstance(data, dict):
            return None
        for f in data.get("facts", [])[:5]:
            if isinstance(f, dict) and f.get("text"):
                try:
                    imp = max(1.0, min(10.0, float(f.get("importance", 5))))
                except (TypeError, ValueError):
                    imp = 5.0
                self.add_fact(npc.name, str(f["text"]), imp, kind="reflection")
        summary = str(data.get("daily_summary", "")).strip()
        if summary:
            self.record_day(npc.name, game_day, summary)
            self.mark_summarized(npc.name, game_day)
            return summary
        return None

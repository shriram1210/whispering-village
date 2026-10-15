"""llm.py - the only file that talks to the AI.
Robust by design: tries several model names, has a timeout, and never crashes the game.
If anything fails, `last_error` explains why and the NPCs switch to built-in offline replies."""
import os
import json
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("GEMINI_API_KEY", "").strip().strip('"').strip("'")
# Your .env MODEL_NAME is tried first, then these (gemini-2.5-flash is being retired by Google).
_env_model = os.getenv("MODEL_NAME", "").strip()
MODELS = list(dict.fromkeys(m for m in (_env_model, "gemini-3.5-flash",
                                        "gemini-flash-latest", "gemini-3.1-flash-lite") if m))
# Optional second backend: any OpenAI-compatible gateway (e.g. OpenCode's).
# Set these in .env to use it INSTEAD of Gemini; leave unset for Gemini.
PROVIDER = os.getenv("LLM_PROVIDER", "gemini").strip().lower()
OCODE_KEY = os.getenv("OPENCODE_API_KEY", "").strip().strip('"').strip("'")
OCODE_BASE = os.getenv("OPENCODE_BASE_URL", "").strip().rstrip("/")
OCODE_MODEL = os.getenv("OPENCODE_MODEL", "").strip() or "nemotron-3.5-lightning-free"
# Generic aliases: any OpenAI-compatible endpoint works (Ollama local, Groq,
# OpenRouter...). LLM_* wins when set, OPENCODE_* stays as fallback.
if os.getenv("LLM_BASE_URL", "").strip():
    OCODE_BASE = os.getenv("LLM_BASE_URL", "").strip().rstrip("/")
if os.getenv("LLM_MODEL", "").strip():
    OCODE_MODEL = os.getenv("LLM_MODEL", "").strip()
if os.getenv("LLM_API_KEY", "").strip():
    OCODE_KEY = os.getenv("LLM_API_KEY", "").strip().strip('"').strip("'")
# User-session tokens (vs service keys) also need the org header — set if auth fails.
OCODE_ORG = os.getenv("OPENCODE_ORG_ID", "").strip()
if _env_model and "gemini" not in _env_model.lower():
    print(f"[llm] MODEL_NAME '{_env_model}' is not a Gemini model. "
          f"Use e.g. gemini-3.5-flash (or delete the line to use the built-in list).")
# Google AI Studio keys start with 'AIza'. Anything else (OpenCode, OpenRouter…)
# is rejected by Google with 400/401 — detect early so the message is actionable.
_KEY_HINT = ""
if API_KEY and not API_KEY.startswith("AIza"):
    _KEY_HINT = ("That key does not look like a Google AI Studio key (Google keys start with 'AIza'). "
                 "Keys from OpenCode or other providers do not work here - get a free one at aistudio.google.com.")
TIMEOUT_MS = 20000

last_error = ""
_good_model = None
_client = None
types = None

try:
    from google import genai
    from google.genai import types
    if API_KEY:
        _client = genai.Client(api_key=API_KEY, http_options=types.HttpOptions(timeout=TIMEOUT_MS))
    else:
        last_error = "No GEMINI_API_KEY found. Check your .env file."
except ImportError:
    last_error = "google-genai is not installed. Run: pip install google-genai"
except Exception as e:
    last_error = f"Could not start AI client: {e}"

_FATAL = ("api key", "api_key", "permission", "unauthenticated", "401", "403", "429", "quota",
          "timed out", "timeout", "deadline", "connect", "network", "resolve")


def _parse(text):
    """Parse model output as JSON. Small local models ramble, so fall back
    to extracting the first balanced {...} block before giving up."""
    text = (text or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text[4:] if text.lower().startswith("json") else text
    text = text.strip()
    try:
        return json.loads(text)
    except ValueError:
        pass
    start = text.find("{")
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        elif ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return json.loads(text[start:i + 1])
    return json.loads(text)  # re-raise the original error


def _ocode_call(system_prompt: str, user_prompt: str):
    """OpenAI-compatible backend (OpenCode gateway): returns dict or None. Never raises."""
    global last_error
    import json as _json
    import urllib.request
    if not OCODE_KEY:
        last_error = "LLM_PROVIDER=opencode but OPENCODE_API_KEY is empty in .env."
        print("[llm]", last_error)
        return None
    if not OCODE_BASE:
        last_error = ("LLM_PROVIDER=opencode but OPENCODE_BASE_URL is empty. "
                      "Set it to your gateway URL, e.g. the OpenAI-compatible base from its docs.")
        print("[llm]", last_error)
        return None
    body = {
        "model": OCODE_MODEL,
        "messages": [{"role": "system", "content": system_prompt},
                     {"role": "user", "content": user_prompt}],
        "temperature": 0.7,
    }
    if "localhost" in OCODE_BASE or "127.0.0.1" in OCODE_BASE:
        # Local servers (Ollama) honor this; some gateways reject it, so local-only.
        body["response_format"] = {"type": "json_object"}
    body = _json.dumps(body).encode()
    headers = {"Content-Type": "application/json", "Authorization": "Bearer " + OCODE_KEY,
               # gateway sits behind Cloudflare: a script UA gets challenged, a browser UA passes
               "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) WhisperingVillage/1.0"}
    if OCODE_ORG:
        headers["x-opencode-org-id"] = OCODE_ORG
    req = urllib.request.Request(OCODE_BASE + "/chat/completions", data=body, headers=headers)
    try:
        # Local models can think slowly: generous timeout (LLM_TIMEOUT_S, default 120s).
        # Cloud bills nothing extra for waiting, so one knob serves both.
        with urllib.request.urlopen(req, timeout=int(os.getenv("LLM_TIMEOUT_S", "120"))) as r:
            payload = _json.loads(r.read().decode())
        text = payload["choices"][0]["message"]["content"]
        return _parse(text)
    except urllib.error.HTTPError as e:
        try:
            detail = e.read().decode()[:200]
        except Exception:
            detail = ""
        last_error = f"opencode gateway ({OCODE_MODEL}): HTTP {e.code} {e.reason} {detail}"
        print("[llm]", last_error)
        return None
    except Exception as e:
        last_error = f"opencode gateway ({OCODE_MODEL}): {str(e)[:140]}"
        print("[llm]", last_error)
        return None


def ask_json(system_prompt: str, user_prompt: str):
    """Returns a dict, or None on failure (see `last_error`)."""
    global last_error, _good_model
    if PROVIDER == "opencode":
        return _ocode_call(system_prompt, user_prompt)
    if _client is None:
        if last_error:
            print("[llm]", last_error)
        return None
    candidates = list(dict.fromkeys(([_good_model] if _good_model else []) + MODELS))
    for model in candidates:
        for _ in range(2):                                   # one retry for bad JSON
            try:
                r = _client.models.generate_content(
                    model=model, contents=user_prompt,
                    config=types.GenerateContentConfig(system_instruction=system_prompt,
                                                       response_mime_type="application/json"))
                data = _parse(r.text)
                _good_model, last_error = model, ""
                return data
            except json.JSONDecodeError:
                last_error = f"{model} returned invalid JSON"
                continue
            except Exception as e:
                last_error = f"{model}: {str(e)[:140]}"
                print("[llm]", last_error)
                if any(k in str(e).lower() for k in _FATAL):
                    if _KEY_HINT and any(k in str(e).lower() for k in ("api key", "api_key", "401", "403", "400")):
                        last_error += " | " + _KEY_HINT
                        print("[llm]", _KEY_HINT)
                    return None                              # key/quota/network problem: other models won't help
                break                                        # model problem: try the next model name
    return None

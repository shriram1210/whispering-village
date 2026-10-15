"""Run this first if the NPCs don't answer properly:  python check_api.py"""
import llm

print("Provider          :", llm.PROVIDER)
print("API key found     :", bool(llm.API_KEY) if llm.PROVIDER != "opencode" else bool(llm.OCODE_KEY))
print("Models to try     :", llm.MODELS if llm.PROVIDER != "opencode" else [llm.OCODE_MODEL + " @ " + (llm.OCODE_BASE or "(no base URL set)")])
r = llm.ask_json("Reply ONLY with JSON.", 'Return exactly: {"ok": true, "msg": "hello from the AI"}')
if r:
    print("\nSUCCESS  ->", r)
    print("Model that works  :", llm._good_model)
    print("\nYour AI connection is fine. If the game still misbehaves, send me the terminal output.")
else:
    print("\nFAILED   ->", llm.last_error)
    print("\nTips:")
    print(" - 'No GEMINI_API_KEY': put GEMINI_API_KEY=your_key in a file named .env next to main.py")
    print(" - 'API key not valid' / 403: create a fresh key at aistudio.google.com")
    print(" - 429 / quota: free-tier limit reached, wait a minute")
    print(" - timeout / connect: check your internet or VPN")
    print(" - not installed: pip install -r requirements.txt")
    print("The game still works without AI (built-in offline replies), just less smart.")
if llm._client:
    try:
        names = [m.name for m in llm._client.models.list() if "flash" in m.name]
        print("\nFlash models your key can see:", names[:12])
    except Exception as e:
        print("\n(could not list models:", str(e)[:100], ")")

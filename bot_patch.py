"""
bot_patch.py — Bot.py changes for v5.7

STEP 1: Add these imports at the top of bot.py (if not already there):
"""
# ADD THESE IMPORTS:
import subprocess
import sys
import os
import time

# ADD A DEFAULT SETTINGS ENTRY for auto-router in your default_settings.py:
#   "auto_router_enabled": False,
#   "auto_router_allowed_models": [],


# STEP 2: Replace the existing sidecar startup block with this.
# Place AFTER bot = commands.Bot(...) and BEFORE bot.load_extension(...)

# ═══════════════════════════════════════════════════════════════
#  Z.ai Sidecar Startup (Pure Python — NO Node.js needed)
# ═══════════════════════════════════════════════════════════════

sidecar_process = None
SIDECAR_PORT = int(os.environ.get("ZAI_SIDECAR_PORT", 3456))

try:
    sidecar_script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "zai_sidecar.py")
    if os.path.exists(sidecar_script):
        sidecar_process = subprocess.Popen(
            [sys.executable, sidecar_script],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
        )
        time.sleep(2)
        if sidecar_process.poll() is None:
            print(f"[Z.ai] Sidecar started on port {SIDECAR_PORT} (PID: {sidecar_process.pid})")
        else:
            _, stderr = sidecar_process.communicate(timeout=5)
            print(f"[Z.ai] Sidecar crashed on start: {stderr.decode()[:300]}")
            sidecar_process = None
    else:
        print("[Z.ai] zai_sidecar.py not found — Z.ai features disabled")
except Exception as e:
    print(f"[Z.ai] Sidecar failed to start: {e}")
    sidecar_process = None


# STEP 3: In your LLM chat call in cogs/chat.py, change the model selection:
# 
#   # OLD:
#   model = settings.get("model", "meta-llama/llama-4-maverick:free")
#   result = await llm_handler.chat(messages, model=model, system_prompt=system_prompt)
#
#   # NEW:
#   auto_router = settings.get("auto_router_enabled", False)
#   allowed_models = settings.get("auto_router_allowed_models", [])
#   model = settings.get("model", "meta-llama/llama-4-maverick:free")
#   result = await llm_handler.chat(
#       messages,
#       model=model,
#       system_prompt=system_prompt,
#       auto_router=auto_router,
#       allowed_models=allowed_models if allowed_models else None,
#   )

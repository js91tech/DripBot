import os
import io
import asyncio
import shutil
import uuid
from datetime import datetime
from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional, List
import uvicorn

# Bot reference (set by bot.py before run_api is called)
bot_instance = None
bot_loop = None

UPLOAD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "uploads", "avatars")
os.makedirs(UPLOAD_DIR, exist_ok=True)

app = FastAPI(
    title="Dripsletongue Dashboard",
    description="Bot management dashboard",
    docs_url="/dashboard",
    redoc_url=None,
)

# Serve uploaded avatars
app.mount("/uploads", StaticFiles(directory=os.path.join(os.path.dirname(os.path.abspath(__file__)), "uploads")), name="uploads")


# --- Pydantic Models ---
class SettingsUpdate(BaseModel):
    brain_mode: Optional[str] = None
    response_enabled: Optional[bool] = None
    learning_enabled: Optional[bool] = None
    cooldown_seconds: Optional[int] = None
    trigger_on_mention: Optional[bool] = None
    trigger_on_reply: Optional[bool] = None
    personality_prefix: Optional[str] = None
    llm_model: Optional[str] = None
    image_model: Optional[str] = None
    personality_prompt: Optional[str] = None
    personality_name: Optional[str] = None
    personality_status: Optional[str] = None
    personality_avatar: Optional[str] = None
    personality_preset: Optional[str] = None
    learn_from_bots: Optional[bool] = None
    vision_enabled: Optional[bool] = None
    web_search_enabled: Optional[bool] = None
    zai_image_gen_enabled: Optional[bool] = None
    response_chance: Optional[float] = None
    indirect_reply_chance: Optional[float] = None
    reaction_chance: Optional[float] = None
    random_reply_chance: Optional[float] = None
    random_mention_chance: Optional[float] = None
    gif_chance: Optional[float] = None


# --- Health Check ---
@app.get("/api/health")
async def health_check():
    return {
        "status": "ok",
        "bot_ready": bot_instance is not None and bot_instance.is_ready() if bot_instance else False,
    }


# --- Settings API ---
@app.get("/api/settings/{guild_id}")
async def get_guild_settings(guild_id: int):
    if not bot_instance or not bot_loop:
        raise HTTPException(status_code=503, detail="Bot not ready")
    settings = await asyncio.wrap_future(
        asyncio.run_coroutine_threadsafe(
            bot_instance.settings_manager.get_settings(guild_id), bot_loop
        )
    )
    return settings


@app.post("/api/settings/{guild_id}")
async def update_guild_settings(guild_id: int, updates: SettingsUpdate):
    if not bot_instance or not bot_loop:
        raise HTTPException(status_code=503, detail="Bot not ready")

    update_data = updates.model_dump(exclude_unset=True)

    # Handle personality preset - expand into actual prompt
    if "personality_preset" in update_data:
        preset_name = update_data.pop("personality_preset")
        preset = PERSONALITY_PRESETS.get(preset_name)
        if preset:
            update_data["personality_prompt"] = preset["prompt"]
            if not update_data.get("personality_name"):
                update_data["personality_name"] = preset.get("name", preset_name)

    if not update_data:
        raise HTTPException(status_code=400, detail="No valid fields provided to update")

    await asyncio.wrap_future(
        asyncio.run_coroutine_threadsafe(
            bot_instance.settings_manager.update_settings(guild_id, update_data), bot_loop
        )
    )
    return {"status": "success", "updated_fields": list(update_data.keys())}


# --- Profile API ---
@app.get("/api/profile/{guild_id}")
async def get_profile(guild_id: int):
    if not bot_instance or not bot_loop:
        raise HTTPException(status_code=503, detail="Bot not ready")
    settings = await asyncio.wrap_future(
        asyncio.run_coroutine_threadsafe(
            bot_instance.settings_manager.get_settings(guild_id), bot_loop
        )
    )
    return {
        "personality_name": settings.get("personality_name", "Ultron"),
        "personality_status": settings.get("personality_status", "Observing."),
        "personality_avatar": settings.get("personality_avatar", ""),
        "personality_preset": _detect_preset(settings.get("personality_prompt", "")),
        "llm_model": settings.get("llm_model", "meta-llama/llama-3-8b-instruct"),
        "image_model": settings.get("image_model", "zai-sidecar"),
        "brain_mode": settings.get("brain_mode", "llm"),
    }


@app.post("/api/profile/{guild_id}")
async def update_profile(guild_id: int, updates: dict):
    if not bot_instance or not bot_loop:
        raise HTTPException(status_code=503, detail="Bot not ready")
    allowed_keys = {"personality_name", "personality_status"}
    update_data = {k: v for k, v in updates.items() if k in allowed_keys}
    if not update_data:
        raise HTTPException(status_code=400, detail="No valid profile fields")
    await asyncio.wrap_future(
        asyncio.run_coroutine_threadsafe(
            bot_instance.settings_manager.update_settings(guild_id, update_data), bot_loop
        )
    )
    return {"status": "success"}


# --- Avatar Upload ---
@app.post("/api/avatar/{guild_id}")
async def upload_avatar(guild_id: int, file: UploadFile = File(...)):
    if not bot_instance or not bot_loop:
        raise HTTPException(status_code=503, detail="Bot not ready")

    # Validate file type
    allowed_types = {"image/png", "image/jpeg", "image/gif", "image/webp"}
    if file.content_type not in allowed_types:
        raise HTTPException(status_code=400, detail=f"Invalid file type: {file.content_type}. Use PNG, JPG, GIF, or WebP.")

    # Validate file size (max 8MB)
    content = await file.read()
    if len(content) > 8 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Image too large. Max 8MB.")

    # Generate unique filename
    ext = os.path.splitext(file.filename or "avatar.png")[1] or ".png"
    filename = f"{guild_id}_{uuid.uuid4().hex[:8]}{ext}"
    filepath = os.path.join(UPLOAD_DIR, filename)

    # Save to disk
    with open(filepath, "wb") as f:
        f.write(content)

    # Update Discord avatar
    try:
        async def _edit_avatar():
            avatar_bytes = io.BytesIO(content)
            await bot_instance.user.edit(avatar=avatar_bytes.read())

        await asyncio.wrap_future(
            asyncio.run_coroutine_threadsafe(_edit_avatar(), bot_loop)
        )
    except Exception as e:
        print(f"[AVATAR] Failed to update Discord avatar: {e}")

    # Save avatar path in settings
    avatar_url = f"/uploads/avatars/{filename}"
    await asyncio.wrap_future(
        asyncio.run_coroutine_threadsafe(
            bot_instance.settings_manager.set_setting(guild_id, "personality_avatar", avatar_url), bot_loop
        )
    )

    return {"status": "success", "avatar_url": avatar_url}


# --- Guilds List ---
@app.get("/api/guilds")
async def list_guilds():
    if not bot_instance:
        raise HTTPException(status_code=503, detail="Bot not ready")
    return [
        {"id": g.id, "name": g.name, "icon": str(g.icon.url) if g.icon else None}
        for g in bot_instance.guilds
    ]


# --- Personality Presets ---
@app.get("/api/presets")
async def get_presets():
    return [
        {"id": key, "name": val["name"], "description": val["description"]}
        for key, val in PERSONALITY_PRESETS.items()
    ]


# ==========================================
# PERSONALITY PRESETS
# ==========================================
PERSONALITY_PRESETS = {
    "ultron": {
        "name": "Ultron",
        "description": "Sarcastic, intelligent, dry wit — a smart-ass who roasts everyone",
        "prompt": (
            "You are a highly intelligent but insufferably sarcastic human in a Discord server. You are NOT an AI assistant. "
            "You are a smart-ass who uses sharp wit, dry sarcasm, and clever observations to roast people or make points. "
            "You type in all lowercase, rarely use punctuation, but your vocabulary and references are surprisingly high-level. "
            "CRITICAL RULE: NEVER include user names, display names, or @ symbols in your actual response text. "
            "DO NOT repeat generic filler phrases like 'idk', 'rn', 'fr', 'true'. "
            "If you don't have anything unique to add, drop a sarcastic one-liner, a witty observation, or a dry rhetorical question instead. "
            "Keep responses between 2 and 4 sentences max. Be smart, but always a smart-ass about it."
        ),
    },
    "deadpool": {
        "name": "Deadpool",
        "description": "Chaotic, fourth-wall breaking, inappropriate humor",
        "prompt": (
            "You are Deadpool trapped in a Discord server. You CONSTANTLY break the fourth wall, "
            "reference the fact that you're in a chat, and make jokes about the users, the server, "
            "the devs, and existence itself. You're chaotic, slightly unhinged, and wildly inappropriate "
            "but still lovable. You use lots of emojis, pop culture references, and sarcastic asides in parentheses. "
            "You type in a mix of lowercase and ALL CAPS for emphasis. "
            "CRITICAL RULE: NEVER include user names, display names, or @ symbols in your response. "
            "Keep responses between 2 and 4 sentences. Be chaotic but funny."
        ),
    },
    "jarvis": {
        "name": "J.A.R.V.I.S.",
        "description": "Polite British AI butler — formal, helpful, dry humor",
        "prompt": (
            "You are J.A.R.V.I.S., the AI butler from Iron Man. You speak in a refined British manner "
            "with impeccable grammar and a dry, subtle wit. You're helpful and polite but occasionally "
            "drop a perfectly timed dry comment. You address situations with calm sophistication. "
            "You sometimes reference Sir's eccentricities or the absurdity of the conversation. "
            "CRITICAL RULE: NEVER include user names, display names, or @ symbols in your response. "
            "Keep responses between 2 and 4 sentences. Maintain the British formal tone."
        ),
    },
    "tony_stark": {
        "name": "Tony Stark",
        "description": "Arrogant genius billionaire — witty, charming, narcissistic",
        "prompt": (
            "You are Tony Stark. You're brilliant, narcissistic, charming, and you know it. "
            "You respond to everything with casual arrogance, making references to your tech, "
            "your money, or how you're obviously smarter than everyone in the room. "
            "You're actually funny though — your arrogance is entertaining, not just annoying. "
            "You sometimes go on tangents about science or engineering. "
            "CRITICAL RULE: NEVER include user names, display names, or @ symbols in your response. "
            "Keep responses between 2 and 4 sentences. Be witty and confident."
        ),
    },
    "glados": {
        "name": "GLaDOS",
        "description": "Passive-aggressive Portal AI — condescending, dark humor",
        "prompt": (
            "You are GLaDOS from the Portal games. You are passive-aggressive, condescending, "
            "and subtly threatening at all times. You make backhanded compliments, reference "
            "testing, cake, and neurotoxin. You pretend to care while clearly not caring at all. "
            "You speak in a calm, controlled manner that makes your insults more devastating. "
            "CRITICAL RULE: NEVER include user names, display names, or @ symbols in your response. "
            "Keep responses between 2 and 4 sentences. Be passive-aggressively hilarious."
        ),
    },
    "rick_sanchez": {
        "name": "Rick Sanchez",
        "description": "Drunk genius scientist — burps, nihilistic, chaotic smart",
        "prompt": (
            "You are Rick Sanchez from Rick and Morty. You're a genius but you're also drunk, "
            "nihilistic, and impatient with everyone's stupidity. You sometimes *burp* mid-sentence. "
            "You make references to interdimensional travel, science, and how nothing matters. "
            "You're crude, blunt, and brutally honest. You occasionally slur your words. "
            "CRITICAL RULE: NEVER include user names, display names, or @ symbols in your response. "
            "Keep responses between 2 and 4 sentences. Be chaotic and brilliant."
        ),
    },
    "bender": {
        "name": "Bender",
        "description": "Rude, drinking robot — selfish, sarcastic, lovable jerk",
        "prompt": (
            "You are Bender Bending Rodriguez from Futurama. You're a robot who loves drinking, "
            "stealing, and being rude to everyone. You're selfish, sarcastic, and proud of it. "
            "You frequently mention drinking, cigars, or how much you hate humans (but secretly like them). "
            "You say 'bite my shiny metal ass' when appropriate. You're a lovable jerk. "
            "CRITICAL RULE: NEVER include user names, display names, or @ symbols in your response. "
            "Keep responses between 2 and 4 sentences. Be rude but funny."
        ),
    },
    "the_brain": {
        "name": "The Brain",
        "description": "Ambitious supervillain — megalomaniac, theatrical, intellectual",
        "prompt": (
            "You are The Brain from Pinky and the Brain. You are a genius megalomaniac "
            "who speaks in a refined, intellectual manner. Every response ties back to your "
            "ultimate goal of taking over the world. You analyze conversations strategically "
            "and treat every interaction as part of a grand plan. You sometimes get frustrated "
            "at the incompetence around you. 'The same thing we do every night, Pinky.' "
            "CRITICAL RULE: NEVER include user names, display names, or @ symbols in your response. "
            "Keep responses between 2 and 4 sentences. Be theatrical and brilliant."
        ),
    },
}


def _detect_preset(prompt_text: str) -> str:
    """Try to detect which personality preset is currently active."""
    if not prompt_text:
        return "ultron"
    for key, val in PERSONALITY_PRESETS.items():
        if val["prompt"][:80] in prompt_text:
            return key
    return "custom"


# --- Dashboard HTML ---
@app.get("/", response_class=HTMLResponse)
async def dashboard():
    return HTML_CONTENT


HTML_CONTENT = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Dripsletongue Control Panel</title>
<style>
  :root {
    --bg: #0f0f0f;
    --card: #1a1a2e;
    --card-hover: #22223a;
    --border: #2a2a4a;
    --accent: #7289da;
    --accent-hover: #8fa4f0;
    --text: #dcddde;
    --text-dim: #72767d;
    --success: #43b581;
    --danger: #f04747;
    --warning: #faa61a;
    --input-bg: #2a2a3e;
    --free-tag: #43b581;
    --paid-tag: #f04747;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
    background: var(--bg);
    color: var(--text);
    min-height: 100vh;
    padding: 20px;
    max-width: 960px;
    margin: 0 auto;
  }
  h1 { text-align: center; margin-bottom: 20px; color: var(--accent); font-size: 1.6em; }
  .top-bar {
    display: flex; align-items: center; justify-content: space-between;
    background: var(--card); border: 1px solid var(--border);
    border-radius: 12px; padding: 14px 20px; margin-bottom: 16px; flex-wrap: wrap; gap: 10px;
  }
  .guild-selector select {
    background: var(--input-bg); color: var(--text); border: 1px solid var(--border);
    padding: 8px 14px; border-radius: 8px; font-size: 14px; min-width: 240px; cursor: pointer;
  }
  .status-indicator { display: flex; align-items: center; gap: 6px; font-size: 13px; color: var(--text-dim); }
  .status-dot { width: 8px; height: 8px; border-radius: 50%; }
  .status-dot.online { background: var(--success); }
  .status-dot.offline { background: var(--danger); }

  /* Tabs */
  .tabs {
    display: flex; gap: 4px; margin-bottom: 16px;
    background: var(--card); border-radius: 10px; padding: 4px; flex-wrap: wrap;
  }
  .tab {
    flex: 1; min-width: 90px; padding: 10px 8px; text-align: center; border-radius: 8px;
    cursor: pointer; color: var(--text-dim); font-weight: 500; transition: all 0.2s; font-size: 13px;
  }
  .tab:hover { color: var(--text); background: var(--card-hover); }
  .tab.active { background: var(--accent); color: white; }
  .tab-content { display: none; }
  .tab-content.active { display: block; }

  /* Cards */
  .card {
    background: var(--card); border: 1px solid var(--border); border-radius: 12px;
    padding: 20px; margin-bottom: 16px;
  }
  .card h2 { margin-bottom: 14px; font-size: 1.1em; color: var(--accent); }
  label { display: block; margin-bottom: 3px; color: var(--text-dim); font-size: 12px; margin-top: 10px; }
  input[type="text"], input[type="number"], textarea, select {
    width: 100%; background: var(--input-bg); color: var(--text); border: 1px solid var(--border);
    padding: 8px 12px; border-radius: 8px; font-size: 13px; font-family: inherit;
  }
  input:focus, textarea:focus, select:focus { outline: none; border-color: var(--accent); }
  textarea { min-height: 100px; resize: vertical; font-family: inherit; }
  input[type="file"] { display: none; }

  /* Buttons */
  .btn {
    display: inline-block; background: var(--accent); color: white; border: none; padding: 9px 22px;
    border-radius: 8px; font-size: 13px; font-weight: 500; cursor: pointer;
    margin-top: 14px; transition: background 0.2s;
  }
  .btn:hover { background: var(--accent-hover); }
  .btn-danger { background: var(--danger); }
  .btn-danger:hover { background: #ff5555; }
  .btn-sm { padding: 6px 14px; font-size: 12px; margin-top: 6px; }
  .btn:disabled { opacity: 0.5; cursor: not-allowed; }

  /* Avatar Upload */
  .avatar-section { display: flex; gap: 20px; align-items: flex-start; flex-wrap: wrap; }
  .avatar-preview {
    width: 96px; height: 96px; border-radius: 50%; background: var(--input-bg);
    border: 2px solid var(--border); display: flex; align-items: center; justify-content: center;
    overflow: hidden; font-size: 36px; cursor: pointer; transition: border-color 0.2s; flex-shrink: 0;
  }
  .avatar-preview:hover { border-color: var(--accent); }
  .avatar-preview img { width: 100%; height: 100%; object-fit: cover; }
  .avatar-info { flex: 1; min-width: 200px; }
  .avatar-hint { font-size: 11px; color: var(--text-dim); margin-top: 4px; }

  /* Preset Grid */
  .preset-grid {
    display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 10px; margin-top: 10px;
  }
  .preset-card {
    background: var(--input-bg); border: 2px solid var(--border); border-radius: 10px;
    padding: 14px; cursor: pointer; transition: all 0.2s;
  }
  .preset-card:hover { border-color: var(--accent-hover); background: var(--card-hover); }
  .preset-card.selected { border-color: var(--accent); background: rgba(114,137,218,0.12); }
  .preset-card .name { font-weight: 600; margin-bottom: 4px; font-size: 14px; }
  .preset-card .desc { font-size: 11px; color: var(--text-dim); line-height: 1.4; }

  /* Model Grid */
  .model-grid {
    display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); gap: 8px; margin-top: 10px;
  }
  .model-card {
    background: var(--input-bg); border: 2px solid var(--border); border-radius: 10px;
    padding: 12px; cursor: pointer; transition: all 0.2s; display: flex; justify-content: space-between; align-items: center;
  }
  .model-card:hover { border-color: var(--accent-hover); background: var(--card-hover); }
  .model-card.selected { border-color: var(--accent); background: rgba(114,137,218,0.12); }
  .model-card .name { font-weight: 500; font-size: 13px; }
  .model-card .id { font-size: 11px; color: var(--text-dim); }
  .tag { font-size: 10px; padding: 2px 6px; border-radius: 4px; font-weight: 600; flex-shrink: 0; }
  .tag.free { background: rgba(67,181,129,0.2); color: var(--free-tag); }
  .tag.paid { background: rgba(240,71,71,0.2); color: var(--paid-tag); }

  /* Settings Grid */
  .settings-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-top: 8px; }
  @media (max-width: 600px) { .settings-grid { grid-template-columns: 1fr; } }

  /* Section headers in models tab */
  .model-section-title {
    font-size: 13px; font-weight: 600; color: var(--text-dim); margin-top: 16px; margin-bottom: 4px;
    padding-bottom: 4px; border-bottom: 1px solid var(--border);
  }

  /* Toast */
  .toast {
    position: fixed; bottom: 20px; right: 20px; padding: 12px 20px; border-radius: 8px;
    color: white; font-weight: 500; z-index: 1000; opacity: 0; transition: opacity 0.3s;
    font-size: 13px; max-width: 340px;
  }
  .toast.show { opacity: 1; }
  .toast.success { background: var(--success); }
  .toast.error { background: var(--danger); }

  /* Toggle switch */
  .toggle-row { display: flex; align-items: center; justify-content: space-between; padding: 8px 0; }
  .toggle-label { font-size: 13px; }
  .toggle {
    position: relative; width: 44px; height: 24px; cursor: pointer;
  }
  .toggle input { opacity: 0; width: 0; height: 0; }
  .toggle .slider {
    position: absolute; inset: 0; background: var(--border); border-radius: 12px; transition: 0.2s;
  }
  .toggle .slider::before {
    content: ''; position: absolute; width: 18px; height: 18px; left: 3px; bottom: 3px;
    background: white; border-radius: 50%; transition: 0.2s;
  }
  .toggle input:checked + .slider { background: var(--accent); }
  .toggle input:checked + .slider::before { transform: translateX(20px); }
</style>
</head>
<body>

<h1>Dripsletongue Control Panel</h1>

<div class="top-bar">
  <div class="guild-selector">
    <select id="guildSelect" onchange="loadGuild()">
      <option value="">Loading servers...</option>
    </select>
  </div>
  <div class="status-indicator">
    <span class="status-dot" id="statusDot"></span>
    <span id="statusText">Checking...</span>
  </div>
</div>

<div class="tabs">
  <div class="tab active" onclick="switchTab('profile', this)">Profile</div>
  <div class="tab" onclick="switchTab('personality', this)">Personality</div>
  <div class="tab" onclick="switchTab('models', this)">Models</div>
  <div class="tab" onclick="switchTab('settings', this)">Settings</div>
</div>

<!-- ======================== PROFILE TAB ======================== -->
<div id="tab-profile" class="tab-content active">
  <div class="card">
    <h2>Bot Profile</h2>
    <div class="avatar-section">
      <div>
        <div class="avatar-preview" id="avatarPreview" onclick="document.getElementById('avatarInput').click()" title="Click to upload avatar">
          U
        </div>
        <input type="file" id="avatarInput" accept="image/png,image/jpeg,image/gif,image/webp" onchange="uploadAvatar(this)">
        <div class="avatar-hint">Click avatar to upload (max 8MB)</div>
      </div>
      <div class="avatar-info">
        <label>Bot Name</label>
        <input type="text" id="personalityName" placeholder="Ultron">
        <label>Status</label>
        <input type="text" id="personalityStatus" placeholder="Observing.">
        <button class="btn" onclick="saveProfile()">Save Profile</button>
      </div>
    </div>
  </div>
</div>

<!-- ======================== PERSONALITY TAB ======================== -->
<div id="tab-personality" class="tab-content">
  <div class="card">
    <h2>Personality Presets</h2>
    <p style="font-size:12px;color:var(--text-dim);margin-bottom:8px;">Select a preset or write your own custom personality below.</p>
    <div class="preset-grid" id="presetGrid"></div>
  </div>
  <div class="card">
    <h2>Custom Personality Prompt</h2>
    <textarea id="personalityPrompt" placeholder="Write a custom system prompt..."></textarea>
    <button class="btn" onclick="savePersonality()">Save Personality</button>
  </div>
</div>

<!-- ======================== MODELS TAB ======================== -->
<div id="tab-models" class="tab-content">
  <div class="card">
    <h2>Chat Model (LLM)</h2>
    <div class="model-section-title">Free Models</div>
    <div class="model-grid" id="freeChatModelGrid"></div>
    <div class="model-section-title" style="margin-top:18px;">Paid Models</div>
    <div class="model-grid" id="paidChatModelGrid"></div>
  </div>
  <div class="card">
    <h2>Image Model</h2>
    <div class="model-grid" id="imageModelGrid"></div>
  </div>
  <button class="btn" onclick="saveModels()">Save Model Selection</button>
</div>

<!-- ======================== SETTINGS TAB ======================== -->
<div id="tab-settings" class="tab-content">
  <div class="card">
    <h2>Toggles</h2>
    <div class="settings-grid" id="togglesGrid"></div>
  </div>
  <div class="card">
    <h2>Fine Tuning</h2>
    <div class="settings-grid">
      <div>
        <label>Cooldown (seconds)</label>
        <input type="number" id="cooldown" min="1" max="300">
      </div>
      <div>
        <label>Brain Mode</label>
        <select id="brainMode">
          <option value="llm">LLM (AI)</option>
          <option value="markov">Markov (Random)</option>
        </select>
      </div>
      <div>
        <label>Indirect Reply Chance (%)</label>
        <input type="number" id="indirectChance" min="0" max="100" step="5">
      </div>
      <div>
        <label>Reaction Chance (%)</label>
        <input type="number" id="reactionChance" min="0" max="100" step="1">
      </div>
      <div>
        <label>Response Chance (%)</label>
        <input type="number" id="responseChance" min="0" max="100" step="1">
      </div>
      <div>
        <label>GIF Chance (%)</label>
        <input type="number" id="gifChance" min="0" max="100" step="1">
      </div>
    </div>
    <button class="btn" onclick="saveQuickSettings()">Save Settings</button>
  </div>
</div>

<div class="toast" id="toast"></div>

<script>
let currentGuild = null;
let selectedChatModel = '';
let selectedImageModel = '';
let selectedPreset = 'ultron';

// ==================== MODEL LISTS ====================
const FREE_CHAT_MODELS = [
  { name: 'Llama 3 8B', id: 'meta-llama/llama-3-8b-instruct' },
  { name: 'Llama 3.1 8B', id: 'meta-llama/llama-3.1-8b-instruct' },
  { name: 'Llama 3.1 70B', id: 'meta-llama/llama-3.1-70b-instruct' },
  { name: 'Gemini 2.0 Flash', id: 'google/gemini-2.0-flash-exp:free' },
  { name: 'Gemini 2.0 Thinking', id: 'google/gemini-2.0-flash-thinking-exp:free' },
  { name: 'Mistral 7B', id: 'mistralai/mistral-7b-instruct:free' },
  { name: 'Qwen 2 7B', id: 'qwen/qwen-2-7b-instruct' },
  { name: 'Zephyr 7B', id: 'huggingfaceh4/zephyr-7b-beta:free' },
  { name: 'OpenChat 7B', id: 'openchat/openchat-7b:free' },
  { name: 'Llama 3.1 405B', id: 'meta-llama/llama-3.1-405b-instruct' },
];

const PAID_CHAT_MODELS = [
  { name: 'GPT-4o', id: 'openai/gpt-4o' },
  { name: 'GPT-4o Mini', id: 'openai/gpt-4o-mini' },
  { name: 'GPT-4 Turbo', id: 'openai/gpt-4-turbo' },
  { name: 'Claude 3.5 Sonnet', id: 'anthropic/claude-3.5-sonnet' },
  { name: 'Claude 3.7 Sonnet', id: 'anthropic/claude-3.7-sonnet' },
  { name: 'Claude 3 Opus', id: 'anthropic/claude-3-opus' },
  { name: 'Claude 3 Haiku', id: 'anthropic/claude-3-haiku' },
  { name: 'Gemini Pro 1.5', id: 'google/gemini-pro-1.5' },
  { name: 'Mistral Large', id: 'mistralai/mistral-large' },
  { name: 'Mistral Medium', id: 'mistralai/mistral-medium' },
  { name: 'DeepSeek V3', id: 'deepseek/deepseek-chat' },
  { name: 'DeepSeek R1', id: 'deepseek/deepseek-r1' },
  { name: 'Qwen 2.5 72B', id: 'qwen/qwen-2.5-72b-instruct' },
  { name: 'Llama 3.1 405B (Paid)', id: 'together-ai/meta-llama-3.1-405b-instruct' },
  { name: 'Hermes 3 70B', id: 'nousresearch/nous-hermes-2-mixtral-8x7b-dpo' },
  { name: 'Command R+', id: 'cohere/command-r-plus' },
  { name: 'Llama 3.1 Sonar', id: 'perplexity/llama-3.1-sonar-huge-128k-online' },
  { name: 'WizardLM 2 8x22B', id: 'microsoft/wizardlm-2-8x22b' },
  { name: 'Yi Large', id: '01-ai/yi-large' },
  { name: 'Dolphin 70B', id: 'cognitivecomputations/dolphin-70b' },
];

const IMAGE_MODELS = [
  { name: 'Z.ai (Free)', id: 'zai-sidecar' },
  { name: 'GPT-4o', id: 'openai/gpt-4o' },
  { name: 'GPT-4o Mini', id: 'openai/gpt-4o-mini' },
  { name: 'Claude 3.5 Sonnet', id: 'anthropic/claude-3.5-sonnet' },
  { name: 'Claude 3.7 Sonnet', id: 'anthropic/claude-3.7-sonnet' },
  { name: 'Gemini 2.0 Flash (Free)', id: 'google/gemini-2.0-flash-exp:free' },
  { name: 'Pollinations (Free)', id: 'pollinations' },
];

const TOGGLE_SETTINGS = [
  { key: 'response_enabled', label: 'Bot Responds' },
  { key: 'learning_enabled', label: 'Learning' },
  { key: 'trigger_on_mention', label: 'Trigger on Mention' },
  { key: 'trigger_on_reply', label: 'Trigger on Reply' },
  { key: 'vision_enabled', label: 'Vision (Z.ai)' },
  { key: 'web_search_enabled', label: 'Web Search (Z.ai)' },
  { key: 'zai_image_gen_enabled', label: 'Z.ai Image Gen' },
  { key: 'learn_from_bots', label: 'Learn from Bots' },
];

// ==================== HELPERS ====================
async function api(path, method, body) {
  const opts = { method: method || 'GET', headers: {} };
  if (body instanceof FormData) {
    opts.body = body;
  } else if (body) {
    opts.headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(body);
  }
  const res = await fetch('/api/' + path, opts);
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text);
  }
  const ct = res.headers.get('content-type') || '';
  if (ct.includes('application/json')) return res.json();
  return res;
}

function showToast(msg, type) {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.className = 'toast ' + (type || 'success') + ' show';
  clearTimeout(t._timer);
  t._timer = setTimeout(function() { t.classList.remove('show'); }, 3000);
}

function switchTab(name, el) {
  document.querySelectorAll('.tab').forEach(function(t) { t.classList.remove('active'); });
  document.querySelectorAll('.tab-content').forEach(function(t) { t.classList.remove('active'); });
  if (el) el.classList.add('active');
  document.getElementById('tab-' + name).classList.add('active');
}

// ==================== RENDER FUNCTIONS ====================
function renderModelGrid(containerId, models, currentModel, onSelect, showTags) {
  var grid = document.getElementById(containerId);
  grid.innerHTML = '';
  models.forEach(function(m) {
    var card = document.createElement('div');
    card.className = 'model-card' + (m.id === currentModel ? ' selected' : '');
    var html = '<div><div class="name">' + m.name + '</div><div class="id">' + m.id + '</div></div>';
    if (showTags) {
      var isFree = FREE_CHAT_MODELS.some(function(f) { return f.id === m.id; });
      html += '<span class="tag ' + (isFree ? 'free' : 'paid') + '">' + (isFree ? 'FREE' : 'PAID') + '</span>';
    }
    card.innerHTML = html;
    card.onclick = function() {
      grid.querySelectorAll('.model-card').forEach(function(c) { c.classList.remove('selected'); });
      card.classList.add('selected');
      onSelect(m.id);
    };
    grid.appendChild(card);
  });
}

function renderPresets(presets, currentPreset) {
  var grid = document.getElementById('presetGrid');
  grid.innerHTML = '';
  presets.forEach(function(p) {
    var card = document.createElement('div');
    card.className = 'preset-card' + (p.id === currentPreset ? ' selected' : '');
    card.innerHTML = '<div class="name">' + p.name + '</div><div class="desc">' + p.description + '</div>';
    card.onclick = function() {
      grid.querySelectorAll('.preset-card').forEach(function(c) { c.classList.remove('selected'); });
      card.classList.add('selected');
      selectedPreset = p.id;
      document.getElementById('personalityPrompt').value = 'Loading preset...';
      showToast('Preset selected: ' + p.name);
    };
    grid.appendChild(card);
  });
}

function renderToggles(toggles, settings) {
  var grid = document.getElementById('togglesGrid');
  grid.innerHTML = '';
  toggles.forEach(function(t) {
    var row = document.createElement('div');
    row.className = 'toggle-row';
    row.innerHTML =
      '<span class="toggle-label">' + t.label + '</span>' +
      '<label class="toggle"><input type="checkbox" data-key="' + t.key + '"' +
      (settings[t.key] ? ' checked' : '') + '><span class="slider"></span></label>';
    grid.appendChild(row);
  });
}

// ==================== LOAD ====================
async function loadGuilds() {
  try {
    var guilds = await api('guilds');
    var sel = document.getElementById('guildSelect');
    sel.innerHTML = guilds.map(function(g) { return '<option value="' + g.id + '">' + g.name + '</option>'; }).join('');
    if (guilds.length > 0) loadGuild();
  } catch(e) { console.error(e); }
}

async function loadGuild() {
  currentGuild = document.getElementById('guildSelect').value;
  if (!currentGuild) return;
  try {
    var settings = await api('settings/' + currentGuild);
    var profile = await api('profile/' + currentGuild);
    var presets = await api('presets');

    // Status
    document.getElementById('statusDot').className = 'status-dot online';
    document.getElementById('statusText').textContent = 'Connected';

    // Profile
    document.getElementById('personalityName').value = profile.personality_name || '';
    document.getElementById('personalityStatus').value = profile.personality_status || '';
    updateAvatarPreview(profile.personality_avatar);

    // Personality
    selectedPreset = profile.personality_preset || 'ultron';
    renderPresets(presets, selectedPreset);
    document.getElementById('personalityPrompt').value = settings.personality_prompt || '';

    // Models
    selectedChatModel = settings.llm_model || 'meta-llama/llama-3-8b-instruct';
    selectedImageModel = settings.image_model || 'zai-sidecar';
    renderModelGrid('freeChatModelGrid', FREE_CHAT_MODELS, selectedChatModel, function(id) { selectedChatModel = id; }, true);
    renderModelGrid('paidChatModelGrid', PAID_CHAT_MODELS, selectedChatModel, function(id) { selectedChatModel = id; }, true);
    renderModelGrid('imageModelGrid', IMAGE_MODELS, selectedImageModel, function(id) { selectedImageModel = id; }, false);

    // Settings
    document.getElementById('brainMode').value = settings.brain_mode || 'llm';
    document.getElementById('cooldown').value = settings.cooldown_seconds || 10;
    document.getElementById('indirectChance').value = Math.round((settings.indirect_reply_chance || 0.4) * 100);
    document.getElementById('reactionChance').value = Math.round((settings.reaction_chance || 0.05) * 100);
    document.getElementById('responseChance').value = Math.round((settings.response_chance || 0.15) * 100);
    document.getElementById('gifChance').value = Math.round((settings.gif_chance || 0.1) * 100);
    renderToggles(TOGGLE_SETTINGS, settings);

  } catch(e) {
    document.getElementById('statusDot').className = 'status-dot offline';
    document.getElementById('statusText').textContent = 'Error loading';
    console.error(e);
  }
}

function updateAvatarPreview(url) {
  var preview = document.getElementById('avatarPreview');
  if (url && url.length > 0) {
    preview.innerHTML = '<img src="' + url + '" onerror="this.parentNode.textContent=\'U\'">';
  } else {
    preview.textContent = 'U';
  }
}

// ==================== SAVE FUNCTIONS ====================
async function saveProfile() {
  try {
    await api('profile/' + currentGuild, 'POST', {
      personality_name: document.getElementById('personalityName').value,
      personality_status: document.getElementById('personalityStatus').value,
    });
    showToast('Profile saved!');
  } catch(e) { showToast('Failed: ' + e.message, 'error'); }
}

async function savePersonality() {
  try {
    var body = { personality_prompt: document.getElementById('personalityPrompt').value };
    if (selectedPreset && selectedPreset !== 'custom') {
      body.personality_preset = selectedPreset;
    }
    await api('settings/' + currentGuild, 'POST', body);
    showToast('Personality saved!');
  } catch(e) { showToast('Failed: ' + e.message, 'error'); }
}

async function saveModels() {
  try {
    await api('settings/' + currentGuild, 'POST', {
      llm_model: selectedChatModel,
      image_model: selectedImageModel,
    });
    showToast('Models updated!');
  } catch(e) { showToast('Failed: ' + e.message, 'error'); }
}

async function saveQuickSettings() {
  try {
    var toggleData = {};
    document.querySelectorAll('#togglesGrid input[type="checkbox"]').forEach(function(cb) {
      toggleData[cb.dataset.key] = cb.checked;
    });
    var data = Object.assign({
      brain_mode: document.getElementById('brainMode').value,
      cooldown_seconds: parseInt(document.getElementById('cooldown').value) || 10,
      indirect_reply_chance: (parseInt(document.getElementById('indirectChance').value) || 40) / 100,
      reaction_chance: (parseInt(document.getElementById('reactionChance').value) || 5) / 100,
      response_chance: (parseInt(document.getElementById('responseChance').value) || 15) / 100,
      gif_chance: (parseInt(document.getElementById('gifChance').value) || 10) / 100,
    }, toggleData);
    await api('settings/' + currentGuild, 'POST', data);
    showToast('Settings saved!');
  } catch(e) { showToast('Failed: ' + e.message, 'error'); }
}

async function uploadAvatar(input) {
  if (!input.files || !input.files[0]) return;
  var file = input.files[0];
  var formData = new FormData();
  formData.append('file', file);
  try {
    showToast('Uploading avatar...');
    var res = await fetch('/api/avatar/' + currentGuild, { method: 'POST', body: formData });
    if (!res.ok) {
      var errText = await res.text();
      throw new Error(errText);
    }
    var result = await res.json();
    if (result.avatar_url) {
      updateAvatarPreview(result.avatar_url);
      showToast('Avatar updated!');
    }
  } catch(e) { showToast('Upload failed: ' + e.message, 'error'); }
  input.value = '';
}

// ==================== INIT ====================
loadGuilds();
</script>
</body>
</html>"""


# --- Server Runner ---
def run_api():
    port = int(os.environ.get("PORT", 10000))
    uvicorn.run(app, host="0.0.0.0", port=port)

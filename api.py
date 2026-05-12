from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from typing import Optional
import uvicorn
import os
import asyncio

# Bot reference (set by bot.py before run_api is called)
bot_instance = None
bot_loop = None

app = FastAPI(
    title="Discord Bot Dashboard",
    description="Internal dashboard to manage bot settings",
    docs_url="/dashboard",
    redoc_url=None
)


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


# --- Health Check ---
@app.get("/api/health")
async def health_check():
    """Health check endpoint for Render and self-ping keep-alive."""
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
    """Get bot profile info for a guild."""
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
        "llm_model": settings.get("llm_model", "meta-llama/llama-3-8b-instruct"),
        "image_model": settings.get("image_model", "openai/gpt-4o"),
    }


@app.post("/api/profile/{guild_id}")
async def update_profile(guild_id: int, updates: dict):
    """Update bot profile fields."""
    if not bot_instance or not bot_loop:
        raise HTTPException(status_code=503, detail="Bot not ready")
    allowed_keys = {"personality_name", "personality_status", "personality_avatar"}
    update_data = {k: v for k, v in updates.items() if k in allowed_keys}
    if not update_data:
        raise HTTPException(status_code=400, detail="No valid profile fields")
    await asyncio.wrap_future(
        asyncio.run_coroutine_threadsafe(
            bot_instance.settings_manager.update_settings(guild_id, update_data), bot_loop
        )
    )
    return {"status": "success"}


# --- Guilds List ---
@app.get("/api/guilds")
async def list_guilds():
    """List all guilds the bot is in."""
    if not bot_instance:
        raise HTTPException(status_code=503, detail="Bot not ready")
    return [
        {"id": g.id, "name": g.name, "icon": str(g.icon.url) if g.icon else None}
        for g in bot_instance.guilds
    ]


# --- Dashboard HTML ---
@app.get("/", response_class=HTMLResponse)
async def dashboard():
    return HTML_CONTENT


HTML_CONTENT = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Dripsletongue Dashboard</title>
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
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
    background: var(--bg);
    color: var(--text);
    min-height: 100vh;
    padding: 20px;
  }
  h1 { text-align: center; margin-bottom: 24px; color: var(--accent); font-size: 1.8em; }
  .guild-selector {
    text-align: center; margin-bottom: 24px;
  }
  .guild-selector select {
    background: var(--input-bg); color: var(--text); border: 1px solid var(--border);
    padding: 10px 16px; border-radius: 8px; font-size: 14px; min-width: 300px; cursor: pointer;
  }
  .tabs {
    display: flex; gap: 4px; margin-bottom: 20px;
    background: var(--card); border-radius: 10px; padding: 4px;
  }
  .tab {
    flex: 1; padding: 12px; text-align: center; border-radius: 8px; cursor: pointer;
    color: var(--text-dim); font-weight: 500; transition: all 0.2s;
  }
  .tab:hover { color: var(--text); background: var(--card-hover); }
  .tab.active { background: var(--accent); color: white; }
  .tab-content { display: none; }
  .tab-content.active { display: block; }
  .card {
    background: var(--card); border: 1px solid var(--border); border-radius: 12px;
    padding: 20px; margin-bottom: 16px;
  }
  .card h2 { margin-bottom: 16px; font-size: 1.2em; color: var(--accent); }
  label { display: block; margin-bottom: 4px; color: var(--text-dim); font-size: 13px; margin-top: 12px; }
  input, textarea, select {
    width: 100%; background: var(--input-bg); color: var(--text); border: 1px solid var(--border);
    padding: 10px 14px; border-radius: 8px; font-size: 14px; font-family: inherit;
  }
  textarea { min-height: 120px; resize: vertical; }
  input:focus, textarea:focus, select:focus { outline: none; border-color: var(--accent); }
  .model-grid {
    display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
    gap: 10px; margin-top: 12px;
  }
  .model-card {
    background: var(--input-bg); border: 2px solid var(--border); border-radius: 10px;
    padding: 14px; cursor: pointer; transition: all 0.2s;
  }
  .model-card:hover { border-color: var(--accent-hover); background: var(--card-hover); }
  .model-card.selected { border-color: var(--accent); background: rgba(114,137,218,0.15); }
  .model-card .name { font-weight: 600; margin-bottom: 4px; }
  .model-card .id { font-size: 12px; color: var(--text-dim); }
  .btn {
    background: var(--accent); color: white; border: none; padding: 10px 24px;
    border-radius: 8px; font-size: 14px; font-weight: 500; cursor: pointer;
    margin-top: 16px; transition: background 0.2s;
  }
  .btn:hover { background: var(--accent-hover); }
  .btn-danger { background: var(--danger); }
  .btn-danger:hover { background: #ff5555; }
  .profile-section { display: flex; gap: 20px; align-items: flex-start; flex-wrap: wrap; }
  .avatar-preview {
    width: 100px; height: 100px; border-radius: 50%; background: var(--input-bg);
    border: 2px solid var(--border); display: flex; align-items: center; justify-content: center;
    overflow: hidden; font-size: 40px;
  }
  .avatar-preview img { width: 100%; height: 100%; object-fit: cover; }
  .toast {
    position: fixed; bottom: 20px; right: 20px; padding: 12px 20px; border-radius: 8px;
    color: white; font-weight: 500; z-index: 1000; opacity: 0; transition: opacity 0.3s;
  }
  .toast.show { opacity: 1; }
  .toast.success { background: var(--success); }
  .toast.error { background: var(--danger); }
  .status-dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 6px; }
  .status-dot.online { background: var(--success); }
  .status-dot.offline { background: var(--danger); }
</style>
</head>
<body>

<h1>Dripsletongue Control Panel</h1>

<div class="guild-selector">
  <select id="guildSelect" onchange="loadGuild()">
    <option value="">Loading servers...</option>
  </select>
  <span id="statusIndicator" style="margin-left: 12px;">
    <span class="status-dot" id="statusDot"></span>
    <span id="statusText" style="color: var(--text-dim); font-size: 13px;">Checking...</span>
  </span>
</div>

<div class="tabs">
  <div class="tab active" onclick="switchTab('profile')">Profile</div>
  <div class="tab" onclick="switchTab('settings')">Settings</div>
  <div class="tab" onclick="switchTab('models')">Models</div>
</div>

<!-- PROFILE TAB -->
<div id="tab-profile" class="tab-content active">
  <div class="card">
    <h2>Bot Profile</h2>
    <div class="profile-section">
      <div>
        <div class="avatar-preview" id="avatarPreview">U</div>
        <label style="margin-top:8px;">Avatar URL</label>
        <input type="text" id="avatarUrl" placeholder="https://..." oninput="updateAvatarPreview()">
      </div>
      <div style="flex:1; min-width: 200px;">
        <label>Name</label>
        <input type="text" id="personalityName" placeholder="Ultron">
        <label>Status</label>
        <input type="text" id="personalityStatus" placeholder="Observing.">
      </div>
    </div>
    <button class="btn" onclick="saveProfile()">Save Profile</button>
  </div>
</div>

<!-- SETTINGS TAB -->
<div id="tab-settings" class="tab-content">
  <div class="card">
    <h2>Personality Prompt</h2>
    <textarea id="personalityPrompt" placeholder="Custom system prompt..."></textarea>
    <button class="btn" onclick="savePersonality()">Save Personality</button>
  </div>
  <div class="card">
    <h2>Quick Settings</h2>
    <div style="display:grid; grid-template-columns: 1fr 1fr; gap: 12px;">
      <div>
        <label>Brain Mode</label>
        <select id="brainMode">
          <option value="llm">LLM (AI)</option>
          <option value="markov">Markov (Random)</option>
        </select>
      </div>
      <div>
        <label>Cooldown (seconds)</label>
        <input type="number" id="cooldown" min="1" max="300">
      </div>
      <div>
        <label>Response Enabled</label>
        <select id="responseEnabled">
          <option value="true">Yes</option>
          <option value="false">No</option>
        </select>
      </div>
      <div>
        <label>Learning Enabled</label>
        <select id="learningEnabled">
          <option value="true">Yes</option>
          <option value="false">No</option>
        </select>
      </div>
      <div>
        <label>Trigger on Mention</label>
        <select id="triggerMention">
          <option value="true">Yes</option>
          <option value="false">No</option>
        </select>
      </div>
      <div>
        <label>Trigger on Reply</label>
        <select id="triggerReply">
          <option value="true">Yes</option>
          <option value="false">No</option>
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
    </div>
    <button class="btn" onclick="saveQuickSettings()">Save Settings</button>
  </div>
</div>

<!-- MODELS TAB -->
<div id="tab-models" class="tab-content">
  <div class="card">
    <h2>Chat Model</h2>
    <div class="model-grid" id="chatModelGrid"></div>
  </div>
  <div class="card">
    <h2>Image Model</h2>
    <div class="model-grid" id="imageModelGrid"></div>
  </div>
  <button class="btn" onclick="saveModels()">Save Model Selection</button>
</div>

<div class="toast" id="toast"></div>

<script>
let currentGuild = null;
let selectedChatModel = '';
let selectedImageModel = '';

const CHAT_MODELS = [
  { name: 'Llama 3 8B (Free)', id: 'meta-llama/llama-3-8b-instruct' },
  { name: 'Llama 3.1 8B (Free)', id: 'meta-llama/llama-3.1-8b-instruct' },
  { name: 'Llama 3.1 70B', id: 'meta-llama/llama-3.1-70b-instruct' },
  { name: 'Claude 3.5 Sonnet', id: 'anthropic/claude-3.5-sonnet' },
  { name: 'Claude 3.7 Sonnet', id: 'anthropic/claude-3.7-sonnet' },
  { name: 'GPT-4o', id: 'openai/gpt-4o' },
  { name: 'GPT-4o Mini', id: 'openai/gpt-4o-mini' },
  { name: 'Gemini 2.0 Flash (Free)', id: 'google/gemini-2.0-flash-exp:free' },
  { name: 'Mistral Large', id: 'mistralai/mistral-large' },
  { name: 'DeepSeek V3', id: 'deepseek/deepseek-chat' },
  { name: 'Qwen 2.5 72B', id: 'qwen/qwen-2.5-72b-instruct' },
  { name: 'Hermes 3 70B', id: 'nousresearch/nous-hermes-2-mixtral-8x7b-dpo' },
];

const IMAGE_MODELS = [
  { name: 'GPT-4o (Best Quality)', id: 'openai/gpt-4o' },
  { name: 'GPT-4o Mini (Cheaper)', id: 'openai/gpt-4o-mini' },
  { name: 'Claude 3.5 Sonnet', id: 'anthropic/claude-3.5-sonnet' },
  { name: 'Claude 3.7 Sonnet', id: 'anthropic/claude-3.7-sonnet' },
  { name: 'Gemini 2.0 Flash (Free)', id: 'google/gemini-2.0-flash-exp:free' },
  { name: 'Pollinations (Always Free)', id: 'pollinations' },
];

async function api(path, method='GET', body=null) {
  const opts = { method, headers: {'Content-Type': 'application/json'} };
  if (body) opts.body = JSON.stringify(body);
  const res = await fetch('/api/' + path, opts);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

function showToast(msg, type='success') {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.className = 'toast ' + type + ' show';
  setTimeout(() => t.classList.remove('show'), 3000);
}

function switchTab(name) {
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
  event.target.classList.add('active');
  document.getElementById('tab-' + name).classList.add('active');
}

function renderModelGrid(containerId, models, currentModel, onSelect) {
  const grid = document.getElementById(containerId);
  grid.innerHTML = '';
  models.forEach(m => {
    const card = document.createElement('div');
    card.className = 'model-card' + (m.id === currentModel ? ' selected' : '');
    card.innerHTML = '<div class="name">' + m.name + '</div><div class="id">' + m.id + '</div>';
    card.onclick = () => {
      grid.querySelectorAll('.model-card').forEach(c => c.classList.remove('selected'));
      card.classList.add('selected');
      onSelect(m.id);
    };
    grid.appendChild(card);
  });
}

function updateAvatarPreview() {
  const url = document.getElementById('avatarUrl').value;
  const preview = document.getElementById('avatarPreview');
  if (url) {
    preview.innerHTML = '<img src="' + url + '" onerror="this.parentNode.textContent=\\'U\\'">';
  } else {
    preview.textContent = 'U';
  }
}

async function loadGuilds() {
  try {
    const guilds = await api('guilds');
    const sel = document.getElementById('guildSelect');
    sel.innerHTML = guilds.map(g => '<option value="' + g.id + '">' + g.name + '</option>').join('');
    if (guilds.length > 0) loadGuild();
  } catch(e) { console.error(e); }
}

async function loadGuild() {
  currentGuild = document.getElementById('guildSelect').value;
  if (!currentGuild) return;
  try {
    const [settings, profile] = await Promise.all([
      api('settings/' + currentGuild),
      api('profile/' + currentGuild),
    ]);

    // Profile
    document.getElementById('personalityName').value = profile.personality_name || '';
    document.getElementById('personalityStatus').value = profile.personality_status || '';
    document.getElementById('avatarUrl').value = profile.personality_avatar || '';
    updateAvatarPreview();

    // Settings
    document.getElementById('personalityPrompt').value = settings.personality_prompt || '';
    document.getElementById('brainMode').value = settings.brain_mode || 'llm';
    document.getElementById('cooldown').value = settings.cooldown_seconds || 10;
    document.getElementById('responseEnabled').value = String(settings.response_enabled);
    document.getElementById('learningEnabled').value = String(settings.learning_enabled);
    document.getElementById('triggerMention').value = String(settings.trigger_on_mention);
    document.getElementById('triggerReply').value = String(settings.trigger_on_reply);
    document.getElementById('indirectChance').value = Math.round((settings.indirect_reply_chance || 0.4) * 100);
    document.getElementById('reactionChance').value = Math.round((settings.reaction_chance || 0.05) * 100);

    // Models
    selectedChatModel = settings.llm_model || 'meta-llama/llama-3-8b-instruct';
    selectedImageModel = settings.image_model || 'openai/gpt-4o';
    renderModelGrid('chatModelGrid', CHAT_MODELS, selectedChatModel, id => selectedChatModel = id);
    renderModelGrid('imageModelGrid', IMAGE_MODELS, selectedImageModel, id => selectedImageModel = id);

    document.getElementById('statusDot').className = 'status-dot online';
    document.getElementById('statusText').textContent = 'Connected';
  } catch(e) {
    document.getElementById('statusDot').className = 'status-dot offline';
    document.getElementById('statusText').textContent = 'Error loading';
    console.error(e);
  }
}

async function saveProfile() {
  try {
    await api('profile/' + currentGuild, 'POST', {
      personality_name: document.getElementById('personalityName').value,
      personality_status: document.getElementById('personalityStatus').value,
      personality_avatar: document.getElementById('avatarUrl').value,
    });
    showToast('Profile saved!');
  } catch(e) { showToast('Failed: ' + e.message, 'error'); }
}

async function savePersonality() {
  try {
    await api('settings/' + currentGuild, 'POST', {
      personality_prompt: document.getElementById('personalityPrompt').value,
    });
    showToast('Personality saved!');
  } catch(e) { showToast('Failed: ' + e.message, 'error'); }
}

async function saveQuickSettings() {
  try {
    await api('settings/' + currentGuild, 'POST', {
      brain_mode: document.getElementById('brainMode').value,
      cooldown_seconds: parseInt(document.getElementById('cooldown').value) || 10,
      response_enabled: document.getElementById('responseEnabled').value === 'true',
      learning_enabled: document.getElementById('learningEnabled').value === 'true',
      trigger_on_mention: document.getElementById('triggerMention').value === 'true',
      trigger_on_reply: document.getElementById('triggerReply').value === 'true',
      indirect_reply_chance: (parseInt(document.getElementById('indirectChance').value) || 40) / 100,
      reaction_chance: (parseInt(document.getElementById('reactionChance').value) || 5) / 100,
    });
    showToast('Settings saved!');
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

loadGuilds();
</script>
</body>
</html>
"""


# --- Server Runner ---
def run_api():
    port = int(os.environ.get("PORT", 10000))
    uvicorn.run(app, host="0.0.0.0", port=port)

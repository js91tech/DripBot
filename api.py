from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from typing import Optional, Any
import uvicorn
import os
import asyncio

# This will hold the reference to your bot instance and its event loop
bot_instance = None
bot_loop = None

app = FastAPI(
    title="Discord Bot Dashboard",
    description="Internal dashboard to manage bot settings",
    docs_url="/docs",
    redoc_url=None
)

# --- Pydantic Models ---


class SettingsUpdate(BaseModel):
    brain_mode: Optional[str] = None
    response_enabled: Optional[bool] = None
    learning_enabled: Optional[bool] = None
    learn_from_bots: Optional[bool] = None
    trigger_on_mention: Optional[bool] = None
    trigger_on_reply: Optional[bool] = None
    markov_order: Optional[int] = None
    min_response_words: Optional[int] = None
    max_response_words: Optional[int] = None
    cooldown_seconds: Optional[int] = None
    conversation_window_seconds: Optional[int] = None
    indirect_reply_chance: Optional[float] = None
    reaction_chance: Optional[float] = None
    random_reply_chance: Optional[float] = None
    random_mention_chance: Optional[float] = None
    gif_chance: Optional[float] = None
    response_chance: Optional[float] = None
    personality_prefix: Optional[str] = None
    llm_model: Optional[str] = None


class ActionRequest(BaseModel):
    action: str  # "reset_data", "load_brain", "reset_all_settings"


# --- Helper ---


async def _run_coro(coro):
    """Safely run a coroutine from the API thread onto the bot's event loop."""
    if not bot_instance or not bot_loop:
        raise HTTPException(status_code=503, detail="Bot not ready")
    return await asyncio.wrap_future(
        asyncio.run_coroutine_threadsafe(coro, bot_loop)
    )


# --- GUI Dashboard (Single-Page App) ---


@app.get("/", response_class=HTMLResponse)
async def dashboard():
    return HTMLResponse(content=DASHBOARD_HTML)


# --- API Routes ---


@app.get("/api/guilds")
async def get_guilds():
    """List all guilds the bot is in, with names and IDs."""
    if not bot_instance or not bot_loop:
        raise HTTPException(status_code=503, detail="Bot not ready")

    guilds = []
    for guild in bot_instance.guilds:
        guilds.append({
            "id": guild.id,
            "name": guild.name,
            "member_count": guild.member_count,
            "icon_url": str(guild.icon.url) if guild.icon else None,
        })
    return guilds


@app.get("/api/settings/{guild_id}")
async def get_guild_settings(guild_id: int):
    """Fetch the current settings for a specific server."""
    settings = await _run_coro(
        bot_instance.settings_manager.get_settings(guild_id)
    )
    return settings


@app.post("/api/settings/{guild_id}")
async def update_guild_settings(guild_id: int, updates: SettingsUpdate):
    """Update settings for a specific server."""
    update_data = updates.model_dump(exclude_unset=True)
    if not update_data:
        raise HTTPException(status_code=400, detail="No valid fields provided to update")

    await _run_coro(
        bot_instance.settings_manager.update_settings(guild_id, update_data)
    )
    return {"status": "success", "updated_fields": list(update_data.keys())}


@app.get("/api/stats/{guild_id}")
async def get_guild_stats(guild_id: int):
    """Fetch stats for a specific server."""
    stats = await _run_coro(
        bot_instance.db.get_stats(guild_id)
    )
    return stats


@app.post("/api/action/{guild_id}")
async def execute_action(guild_id: int, req: ActionRequest):
    """Execute a dashboard action like reset data or load brain."""
    if req.action == "reset_data":
        chat_cog = bot_instance.get_cog("Chat")
        if chat_cog and guild_id in chat_cog.chains:
            del chat_cog.chains[guild_id]
        await _run_coro(bot_instance.db.delete_guild_data(guild_id))
        await _run_coro(bot_instance.settings_manager.reset_all(guild_id))
        return {"status": "success", "action": "reset_data"}

    elif req.action == "load_brain":
        try:
            with open("training_data.txt", "r", encoding="utf-8") as f:
                lines = f.readlines()
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="training_data.txt not found")

        from engine.markov import MarkovChain

        settings = await _run_coro(bot_instance.settings_manager.get_settings(guild_id))
        chat_cog = bot_instance.get_cog("Chat")
        if not chat_cog:
            raise HTTPException(status_code=500, detail="Chat cog not loaded")

        chain = await _run_coro(chat_cog.get_chain(guild_id, settings["markov_order"]))
        learned_count = 0
        for line in lines:
            clean_line = line.strip()
            if clean_line:
                chain.learn(clean_line)
                learned_count += 1
        await _run_coro(bot_instance.db.save_full_chain(guild_id, chain.to_db_dict()))
        await _run_coro(bot_instance.db.increment_stat(guild_id, "messages_learned", learned_count))
        return {"status": "success", "action": "load_brain", "lines_learned": learned_count}

    elif req.action == "reset_all_settings":
        await _run_coro(bot_instance.settings_manager.reset_all(guild_id))
        return {"status": "success", "action": "reset_all_settings"}

    else:
        raise HTTPException(status_code=400, detail=f"Unknown action: {req.action}")


@app.get("/api/bot_status")
async def bot_status():
    """Get bot connection status."""
    if not bot_instance or not bot_instance.is_ready():
        return {"status": "offline"}
    return {
        "status": "online",
        "bot_name": str(bot_instance.user),
        "bot_id": bot_instance.user.id if bot_instance.user else None,
        "guild_count": len(bot_instance.guilds),
        "latency_ms": round(bot_instance.latency * 1000, 1),
    }


# --- Server Runner ---


def run_api():
    """Runs the web server in a separate thread."""
    port = int(os.environ.get("PORT", 10000))
    uvicorn.run(app, host="0.0.0.0", port=port)


# =============================================================================
# DASHBOARD HTML — Full GUI Single-Page App
# =============================================================================

DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Bot Dashboard</title>
<style>
  :root {
    --bg-primary: #1a1b2e;
    --bg-secondary: #232440;
    --bg-card: #2a2b4a;
    --bg-input: #1e1f38;
    --accent: #7289da;
    --accent-hover: #5b72c4;
    --accent-green: #43b581;
    --accent-red: #f04747;
    --accent-orange: #faa61a;
    --text-primary: #dcddde;
    --text-secondary: #96989d;
    --text-muted: #72767d;
    --border: #3e3f5e;
    --radius: 8px;
  }

  * { margin: 0; padding: 0; box-sizing: border-box; }

  body {
    font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
    background: var(--bg-primary);
    color: var(--text-primary);
    min-height: 100vh;
  }

  /* Top Nav */
  .topbar {
    background: var(--bg-secondary);
    border-bottom: 1px solid var(--border);
    padding: 12px 24px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    position: sticky;
    top: 0;
    z-index: 100;
  }
  .topbar h1 {
    font-size: 18px;
    font-weight: 600;
    color: var(--accent);
  }
  .status-pill {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 4px 12px;
    border-radius: 20px;
    font-size: 12px;
    font-weight: 600;
  }
  .status-pill.online { background: rgba(67,181,129,0.15); color: var(--accent-green); }
  .status-pill.offline { background: rgba(240,71,71,0.15); color: var(--accent-red); }
  .status-dot { width: 8px; height: 8px; border-radius: 50%; }
  .status-pill.online .status-dot { background: var(--accent-green); }
  .status-pill.offline .status-dot { background: var(--accent-red); }

  /* Layout */
  .container { max-width: 1200px; margin: 0 auto; padding: 24px; }

  /* Guild Selector */
  .guild-selector {
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 20px;
    margin-bottom: 24px;
  }
  .guild-selector label {
    display: block;
    font-size: 12px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    color: var(--text-secondary);
    margin-bottom: 8px;
  }
  .guild-select-wrap {
    display: flex;
    align-items: center;
    gap: 12px;
  }
  .guild-icon {
    width: 48px;
    height: 48px;
    border-radius: 50%;
    background: var(--accent);
    display: flex;
    align-items: center;
    justify-content: center;
    font-weight: 700;
    font-size: 18px;
    color: white;
    flex-shrink: 0;
    overflow: hidden;
  }
  .guild-icon img { width: 100%; height: 100%; object-fit: cover; border-radius: 50%; }
  select {
    flex: 1;
    background: var(--bg-input);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    color: var(--text-primary);
    padding: 12px 16px;
    font-size: 15px;
    appearance: none;
    cursor: pointer;
    outline: none;
    transition: border-color 0.2s;
  }
  select:hover { border-color: var(--accent); }
  select:focus { border-color: var(--accent); box-shadow: 0 0 0 2px rgba(114,137,218,0.25); }

  /* Stats Bar */
  .stats-bar {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
    gap: 12px;
    margin-bottom: 24px;
  }
  .stat-card {
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 16px;
    text-align: center;
  }
  .stat-card .stat-value {
    font-size: 28px;
    font-weight: 700;
    color: var(--accent);
  }
  .stat-card .stat-label {
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    color: var(--text-secondary);
    margin-top: 4px;
  }

  /* Sections Grid */
  .sections-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(360px, 1fr));
    gap: 16px;
  }

  /* Card */
  .card {
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    overflow: hidden;
  }
  .card-header {
    padding: 14px 20px;
    border-bottom: 1px solid var(--border);
    font-size: 14px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    color: var(--text-secondary);
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .card-body { padding: 16px 20px; }

  /* Toggle Switch */
  .setting-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 10px 0;
    border-bottom: 1px solid rgba(62,63,94,0.4);
  }
  .setting-row:last-child { border-bottom: none; }
  .setting-label {
    font-size: 14px;
    color: var(--text-primary);
  }
  .setting-desc {
    font-size: 11px;
    color: var(--text-muted);
    margin-top: 2px;
  }

  .toggle {
    position: relative;
    width: 44px;
    height: 24px;
    cursor: pointer;
    flex-shrink: 0;
  }
  .toggle input { opacity: 0; width: 0; height: 0; }
  .toggle .slider {
    position: absolute;
    inset: 0;
    background: var(--bg-input);
    border: 1px solid var(--border);
    border-radius: 24px;
    transition: 0.25s;
  }
  .toggle .slider::before {
    content: '';
    position: absolute;
    width: 18px;
    height: 18px;
    left: 2px;
    top: 2px;
    background: var(--text-secondary);
    border-radius: 50%;
    transition: 0.25s;
  }
  .toggle input:checked + .slider {
    background: var(--accent-green);
    border-color: var(--accent-green);
  }
  .toggle input:checked + .slider::before {
    transform: translateX(20px);
    background: white;
  }

  /* Dropdown / Select in cards */
  .card select {
    width: 100%;
    padding: 8px 12px;
    font-size: 13px;
  }

  /* Slider */
  .slider-row { padding: 10px 0; border-bottom: 1px solid rgba(62,63,94,0.4); }
  .slider-row:last-child { border-bottom: none; }
  .slider-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 6px;
  }
  .slider-label { font-size: 14px; }
  .slider-value {
    font-size: 13px;
    font-weight: 700;
    color: var(--accent);
    min-width: 50px;
    text-align: right;
  }
  input[type="range"] {
    -webkit-appearance: none;
    width: 100%;
    height: 6px;
    border-radius: 3px;
    background: var(--bg-input);
    outline: none;
  }
  input[type="range"]::-webkit-slider-thumb {
    -webkit-appearance: none;
    width: 18px;
    height: 18px;
    border-radius: 50%;
    background: var(--accent);
    cursor: pointer;
    border: 2px solid var(--bg-card);
    box-shadow: 0 1px 3px rgba(0,0,0,0.3);
  }
  input[type="range"]::-moz-range-thumb {
    width: 18px;
    height: 18px;
    border-radius: 50%;
    background: var(--accent);
    cursor: pointer;
    border: 2px solid var(--bg-card);
  }

  /* Text Input */
  .text-input {
    width: 100%;
    background: var(--bg-input);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    color: var(--text-primary);
    padding: 8px 12px;
    font-size: 13px;
    outline: none;
    transition: border-color 0.2s;
  }
  .text-input:focus { border-color: var(--accent); box-shadow: 0 0 0 2px rgba(114,137,218,0.25); }

  /* Buttons */
  .btn {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 6px;
    padding: 10px 20px;
    border-radius: var(--radius);
    font-size: 13px;
    font-weight: 600;
    cursor: pointer;
    border: none;
    transition: all 0.2s;
  }
  .btn:active { transform: scale(0.97); }
  .btn-primary { background: var(--accent); color: white; }
  .btn-primary:hover { background: var(--accent-hover); }
  .btn-danger { background: var(--accent-red); color: white; }
  .btn-danger:hover { background: #d63b3b; }
  .btn-warning { background: var(--accent-orange); color: #1a1b2e; }
  .btn-warning:hover { background: #e09515; }
  .btn-success { background: var(--accent-green); color: white; }
  .btn-success:hover { background: #3aa374; }
  .btn-group { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 12px; }
  .btn-full { width: 100%; }

  /* Actions Card */
  .actions-grid { display: flex; flex-direction: column; gap: 10px; }
  .action-item {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 12px 0;
    border-bottom: 1px solid rgba(62,63,94,0.4);
  }
  .action-item:last-child { border-bottom: none; }
  .action-info .action-title { font-size: 14px; font-weight: 600; }
  .action-info .action-desc { font-size: 11px; color: var(--text-muted); margin-top: 2px; }

  /* Toast */
  .toast-container {
    position: fixed;
    bottom: 24px;
    right: 24px;
    z-index: 9999;
    display: flex;
    flex-direction: column;
    gap: 8px;
  }
  .toast {
    padding: 12px 20px;
    border-radius: var(--radius);
    font-size: 13px;
    font-weight: 600;
    color: white;
    box-shadow: 0 4px 12px rgba(0,0,0,0.4);
    animation: slideIn 0.3s ease-out;
    max-width: 360px;
  }
  .toast.success { background: var(--accent-green); }
  .toast.error { background: var(--accent-red); }
  .toast.info { background: var(--accent); }
  @keyframes slideIn { from { transform: translateX(100%); opacity: 0; } to { transform: translateX(0); opacity: 1; } }

  /* Loading overlay */
  .loading-overlay {
    position: fixed;
    inset: 0;
    background: rgba(26,27,46,0.8);
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 200;
  }
  .spinner {
    width: 40px; height: 40px;
    border: 3px solid var(--border);
    border-top-color: var(--accent);
    border-radius: 50%;
    animation: spin 0.8s linear infinite;
  }
  @keyframes spin { to { transform: rotate(360deg); } }

  /* Chattiness visual */
  .chattiness-bar {
    height: 8px;
    border-radius: 4px;
    background: var(--bg-input);
    overflow: hidden;
    margin-top: 8px;
  }
  .chattiness-fill {
    height: 100%;
    border-radius: 4px;
    background: linear-gradient(90deg, var(--accent-green), var(--accent-orange), var(--accent-red));
    transition: width 0.3s;
  }

  /* Responsive */
  @media (max-width: 768px) {
    .sections-grid { grid-template-columns: 1fr; }
    .stats-bar { grid-template-columns: repeat(2, 1fr); }
  }
</style>
</head>
<body>

<div class="topbar">
  <h1>Bot Dashboard</h1>
  <div id="statusPill" class="status-pill offline">
    <span class="status-dot"></span>
    <span id="statusText">Connecting...</span>
  </div>
</div>

<div class="container">
  <!-- Guild Selector -->
  <div class="guild-selector">
    <label>Select Server</label>
    <div class="guild-select-wrap">
      <div class="guild-icon" id="guildIcon">?</div>
      <select id="guildSelect" onchange="onGuildChange()">
        <option value="">-- Select a server --</option>
      </select>
    </div>
  </div>

  <!-- Stats Bar -->
  <div class="stats-bar">
    <div class="stat-card">
      <div class="stat-value" id="statLearned">0</div>
      <div class="stat-label">Messages Learned</div>
    </div>
    <div class="stat-card">
      <div class="stat-value" id="statSent">0</div>
      <div class="stat-label">Messages Sent</div>
    </div>
    <div class="stat-card">
      <div class="stat-value" id="statLatency">--</div>
      <div class="stat-label">Latency (ms)</div>
    </div>
    <div class="stat-card">
      <div class="stat-value" id="statGuilds">0</div>
      <div class="stat-label">Servers</div>
    </div>
  </div>

  <!-- Settings Grid -->
  <div class="sections-grid">
    <!-- Brain Mode -->
    <div class="card">
      <div class="card-header">Brain Mode</div>
      <div class="card-body">
        <div class="setting-row">
          <div>
            <div class="setting-label">Mode</div>
            <div class="setting-desc">How the bot generates responses</div>
          </div>
        </div>
        <select id="brainMode" onchange="saveSetting('brain_mode', this.value)">
          <option value="llm">LLM (Coherent, Human-like)</option>
          <option value="markov">Markov (Free, Silly, Random)</option>
        </select>
        <div class="setting-row" style="margin-top:12px">
          <div>
            <div class="setting-label">LLM Model</div>
            <div class="setting-desc">OpenRouter model for LLM mode</div>
          </div>
        </div>
        <select id="llmModel" onchange="saveSetting('llm_model', this.value)">
          <option value="meta-llama/llama-3-8b-instruct">Llama 3 8B (Default)</option>
          <option value="meta-llama/llama-3-70b-instruct">Llama 3 70B</option>
          <option value="mistralai/mistral-7b-instruct">Mistral 7B</option>
          <option value="mistralai/mixtral-8x7b-instruct">Mixtral 8x7B</option>
          <option value="nousresearch/nous-hermes-2-mixtral-8x7b-dpo">Nous Hermes 2 Mixtral</option>
          <option value="google/gemma-2-9b-it">Gemma 2 9B</option>
          <option value="microsoft/wizardlm-2-8x22b">WizardLM 2 8x22B</option>
        </select>
      </div>
    </div>

    <!-- Toggles -->
    <div class="card">
      <div class="card-header">Quick Toggles</div>
      <div class="card-body">
        <div class="setting-row">
          <div>
            <div class="setting-label">Responses</div>
            <div class="setting-desc">Bot will reply to messages</div>
          </div>
          <label class="toggle">
            <input type="checkbox" id="responseEnabled" onchange="saveSetting('response_enabled', this.checked)">
            <span class="slider"></span>
          </label>
        </div>
        <div class="setting-row">
          <div>
            <div class="setting-label">Learning</div>
            <div class="setting-desc">Bot learns from messages</div>
          </div>
          <label class="toggle">
            <input type="checkbox" id="learningEnabled" onchange="saveSetting('learning_enabled', this.checked)">
            <span class="slider"></span>
          </label>
        </div>
        <div class="setting-row">
          <div>
            <div class="setting-label">Learn from Bots</div>
            <div class="setting-desc">Include messages from other bots</div>
          </div>
          <label class="toggle">
            <input type="checkbox" id="learnFromBots" onchange="saveSetting('learn_from_bots', this.checked)">
            <span class="slider"></span>
          </label>
        </div>
        <div class="setting-row">
          <div>
            <div class="setting-label">Trigger on Mention</div>
            <div class="setting-desc">Respond when @mentioned</div>
          </div>
          <label class="toggle">
            <input type="checkbox" id="triggerOnMention" onchange="saveSetting('trigger_on_mention', this.checked)">
            <span class="slider"></span>
          </label>
        </div>
        <div class="setting-row">
          <div>
            <div class="setting-label">Trigger on Reply</div>
            <div class="setting-desc">Respond when someone replies to bot</div>
          </div>
          <label class="toggle">
            <input type="checkbox" id="triggerOnReply" onchange="saveSetting('trigger_on_reply', this.checked)">
            <span class="slider"></span>
          </label>
        </div>
      </div>
    </div>

    <!-- Chattiness -->
    <div class="card">
      <div class="card-header">Chattiness</div>
      <div class="card-body">
        <div class="slider-row">
          <div class="slider-header">
            <span class="slider-label">Response Chance</span>
            <span class="slider-value" id="responseChanceVal">15%</span>
          </div>
          <input type="range" id="responseChance" min="0" max="100" value="15"
            oninput="updateSliderDisplay('responseChance','responseChanceVal','%')"
            onchange="saveSetting('response_chance', this.value / 100)">
          <div class="chattiness-bar">
            <div class="chattiness-fill" id="chattinessFill" style="width:15%"></div>
          </div>
        </div>
        <div class="slider-row">
          <div class="slider-header">
            <span class="slider-label">Indirect Reply Chance</span>
            <span class="slider-value" id="indirectReplyChanceVal">40%</span>
          </div>
          <input type="range" id="indirectReplyChance" min="0" max="100" value="40"
            oninput="updateSliderDisplay('indirectReplyChance','indirectReplyChanceVal','%')"
            onchange="saveSetting('indirect_reply_chance', this.value / 100)">
        </div>
        <div class="slider-row">
          <div class="slider-header">
            <span class="slider-label">Random Reply Chance</span>
            <span class="slider-value" id="randomReplyChanceVal">30%</span>
          </div>
          <input type="range" id="randomReplyChance" min="0" max="100" value="30"
            oninput="updateSliderDisplay('randomReplyChance','randomReplyChanceVal','%')"
            onchange="saveSetting('random_reply_chance', this.value / 100)">
        </div>
        <div class="slider-row">
          <div class="slider-header">
            <span class="slider-label">Random Mention Chance</span>
            <span class="slider-value" id="randomMentionChanceVal">10%</span>
          </div>
          <input type="range" id="randomMentionChance" min="0" max="100" value="10"
            oninput="updateSliderDisplay('randomMentionChance','randomMentionChanceVal','%')"
            onchange="saveSetting('random_mention_chance', this.value / 100)">
        </div>
      </div>
    </div>

    <!-- Behavior -->
    <div class="card">
      <div class="card-header">Behavior</div>
      <div class="card-body">
        <div class="slider-row">
          <div class="slider-header">
            <span class="slider-label">Cooldown (seconds)</span>
            <span class="slider-value" id="cooldownSecondsVal">10s</span>
          </div>
          <input type="range" id="cooldownSeconds" min="1" max="120" value="10"
            oninput="updateSliderDisplay('cooldownSeconds','cooldownSecondsVal','s')"
            onchange="saveSetting('cooldown_seconds', parseInt(this.value))">
        </div>
        <div class="slider-row">
          <div class="slider-header">
            <span class="slider-label">Reaction Chance</span>
            <span class="slider-value" id="reactionChanceVal">5%</span>
          </div>
          <input type="range" id="reactionChance" min="0" max="50" value="5"
            oninput="updateSliderDisplay('reactionChance','reactionChanceVal','%')"
            onchange="saveSetting('reaction_chance', this.value / 100)">
        </div>
        <div class="slider-row">
          <div class="slider-header">
            <span class="slider-label">GIF Chance</span>
            <span class="slider-value" id="gifChanceVal">10%</span>
          </div>
          <input type="range" id="gifChance" min="0" max="100" value="10"
            oninput="updateSliderDisplay('gifChance','gifChanceVal','%')"
            onchange="saveSetting('gif_chance', this.value / 100)">
        </div>
        <div class="slider-row">
          <div class="slider-header">
            <span class="slider-label">Conversation Window</span>
            <span class="slider-value" id="convWindowVal">120s</span>
          </div>
          <input type="range" id="conversationWindowSeconds" min="30" max="600" value="120" step="10"
            oninput="updateSliderDisplay('conversationWindowSeconds','convWindowVal','s')"
            onchange="saveSetting('conversation_window_seconds', parseInt(this.value))">
        </div>
        <div class="slider-row">
          <div class="slider-header">
            <span class="slider-label">Min Response Words</span>
            <span class="slider-value" id="minWordsVal">3</span>
          </div>
          <input type="range" id="minResponseWords" min="1" max="15" value="3"
            oninput="updateSliderDisplay('minResponseWords','minWordsVal','')"
            onchange="saveSetting('min_response_words', parseInt(this.value))">
        </div>
        <div class="slider-row">
          <div class="slider-header">
            <span class="slider-label">Max Response Words</span>
            <span class="slider-value" id="maxWordsVal">25</span>
          </div>
          <input type="range" id="maxResponseWords" min="5" max="100" value="25"
            oninput="updateSliderDisplay('maxResponseWords','maxWordsVal','')"
            onchange="saveSetting('max_response_words', parseInt(this.value))">
        </div>
      </div>
    </div>

    <!-- Personality -->
    <div class="card">
      <div class="card-header">Personality</div>
      <div class="card-body">
        <div class="setting-row">
          <div>
            <div class="setting-label">Personality Prefix</div>
            <div class="setting-desc">Added before every Markov response</div>
          </div>
        </div>
        <input class="text-input" id="personalityPrefix" type="text"
          placeholder="e.g., [BOT] or leave empty"
          onblur="saveSetting('personality_prefix', this.value)">
        <div class="slider-row" style="margin-top: 16px">
          <div class="slider-header">
            <span class="slider-label">Markov Order</span>
            <span class="slider-value" id="markovOrderVal">2</span>
          </div>
          <input type="range" id="markovOrder" min="1" max="4" value="2"
            oninput="updateSliderDisplay('markovOrder','markovOrderVal','')"
            onchange="saveSetting('markov_order', parseInt(this.value))">
        </div>
      </div>
    </div>

    <!-- Danger Zone -->
    <div class="card">
      <div class="card-header" style="color: var(--accent-red)">Danger Zone</div>
      <div class="card-body">
        <div class="actions-grid">
          <div class="action-item">
            <div class="action-info">
              <div class="action-title">Load Starter Brain</div>
              <div class="action-desc">Import training_data.txt into this server</div>
            </div>
            <button class="btn btn-warning" onclick="executeAction('load_brain')">Load Brain</button>
          </div>
          <div class="action-item">
            <div class="action-info">
              <div class="action-title">Reset Settings</div>
              <div class="action-desc">Restore all settings to defaults</div>
            </div>
            <button class="btn btn-warning" onclick="executeAction('reset_all_settings')">Reset Settings</button>
          </div>
          <div class="action-item">
            <div class="action-info">
              <div class="action-title">Nuke All Data</div>
              <div class="action-desc">Delete ALL learned data AND settings</div>
            </div>
            <button class="btn btn-danger" onclick="executeAction('reset_data')">Nuke Data</button>
          </div>
        </div>
      </div>
    </div>
  </div>
</div>

<!-- Toast Container -->
<div class="toast-container" id="toastContainer"></div>

<script>
let currentGuildId = null;

// --- Toast Notifications ---
function showToast(message, type = 'info') {
  const container = document.getElementById('toastContainer');
  const toast = document.createElement('div');
  toast.className = `toast ${type}`;
  toast.textContent = message;
  container.appendChild(toast);
  setTimeout(() => { toast.remove(); }, 3000);
}

// --- Bot Status ---
async function fetchBotStatus() {
  try {
    const resp = await fetch('/api/bot_status');
    const data = await resp.json();
    const pill = document.getElementById('statusPill');
    const text = document.getElementById('statusText');
    if (data.status === 'online') {
      pill.className = 'status-pill online';
      text.textContent = `${data.bot_name} | ${data.latency_ms}ms`;
      document.getElementById('statLatency').textContent = data.latency_ms;
      document.getElementById('statGuilds').textContent = data.guild_count;
    } else {
      pill.className = 'status-pill offline';
      text.textContent = 'Offline';
    }
  } catch (e) {
    document.getElementById('statusText').textContent = 'Error';
  }
}

// --- Guild List ---
async function fetchGuilds() {
  try {
    const resp = await fetch('/api/guilds');
    const guilds = await resp.json();
    const select = document.getElementById('guildSelect');
    select.innerHTML = '<option value="">-- Select a server --</option>';
    for (const g of guilds) {
      const opt = document.createElement('option');
      opt.value = g.id;
      opt.textContent = `${g.name} (${g.member_count} members)`;
      select.appendChild(opt);
    }
  } catch (e) {
    console.error('Failed to fetch guilds:', e);
  }
}

function onGuildChange() {
  const select = document.getElementById('guildSelect');
  const guildId = select.value;
  if (!guildId) {
    currentGuildId = null;
    return;
  }
  currentGuildId = parseInt(guildId);

  // Update guild icon
  const selectedOption = select.options[select.selectedIndex];
  const name = selectedOption.textContent.split(' (')[0];
  const iconEl = document.getElementById('guildIcon');
  iconEl.innerHTML = name.charAt(0).toUpperCase();

  loadSettings();
  loadStats();
}

// --- Settings ---
async function loadSettings() {
  if (!currentGuildId) return;
  try {
    const resp = await fetch(`/api/settings/${currentGuildId}`);
    const settings = await resp.json();
    applySettingsToUI(settings);
  } catch (e) {
    showToast('Failed to load settings', 'error');
  }
}

function applySettingsToUI(s) {
  // Dropdowns
  document.getElementById('brainMode').value = s.brain_mode || 'llm';
  document.getElementById('llmModel').value = s.llm_model || 'meta-llama/llama-3-8b-instruct';

  // Toggles
  document.getElementById('responseEnabled').checked = !!s.response_enabled;
  document.getElementById('learningEnabled').checked = !!s.learning_enabled;
  document.getElementById('learnFromBots').checked = !!s.learn_from_bots;
  document.getElementById('triggerOnMention').checked = !!s.trigger_on_mention;
  document.getElementById('triggerOnReply').checked = !!s.trigger_on_reply;

  // Sliders (percentages stored as 0-1)
  setSlider('responseChance', Math.round((s.response_chance || 0.15) * 100), 'responseChanceVal', '%');
  setSlider('indirectReplyChance', Math.round((s.indirect_reply_chance || 0.4) * 100), 'indirectReplyChanceVal', '%');
  setSlider('randomReplyChance', Math.round((s.random_reply_chance || 0.3) * 100), 'randomReplyChanceVal', '%');
  setSlider('randomMentionChance', Math.round((s.random_mention_chance || 0.1) * 100), 'randomMentionChanceVal', '%');
  setSlider('reactionChance', Math.round((s.reaction_chance || 0.05) * 100), 'reactionChanceVal', '%');
  setSlider('gifChance', Math.round((s.gif_chance || 0.1) * 100), 'gifChanceVal', '%');
  setSlider('cooldownSeconds', s.cooldown_seconds || 10, 'cooldownSecondsVal', 's');
  setSlider('conversationWindowSeconds', s.conversation_window_seconds || 120, 'convWindowVal', 's');
  setSlider('minResponseWords', s.min_response_words || 3, 'minWordsVal', '');
  setSlider('maxResponseWords', s.max_response_words || 25, 'maxWordsVal', '');
  setSlider('markovOrder', s.markov_order || 2, 'markovOrderVal', '');

  // Chattiness bar
  const rc = Math.round((s.response_chance || 0.15) * 100);
  document.getElementById('chattinessFill').style.width = rc + '%';

  // Text inputs
  document.getElementById('personalityPrefix').value = s.personality_prefix || '';
}

function setSlider(sliderId, value, displayId, suffix) {
  const slider = document.getElementById(sliderId);
  slider.value = value;
  document.getElementById(displayId).textContent = value + suffix;
}

function updateSliderDisplay(sliderId, displayId, suffix) {
  const val = document.getElementById(sliderId).value;
  document.getElementById(displayId).textContent = val + suffix;
  if (sliderId === 'responseChance') {
    document.getElementById('chattinessFill').style.width = val + '%';
  }
}

// --- Save Settings ---
async function saveSetting(key, value) {
  if (!currentGuildId) {
    showToast('Select a server first!', 'error');
    return;
  }
  try {
    const body = {};
    body[key] = value;
    const resp = await fetch(`/api/settings/${currentGuildId}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    const data = await resp.json();
    if (data.status === 'success') {
      showToast(`Updated: ${key}`, 'success');
    } else {
      showToast(`Failed to update ${key}`, 'error');
    }
  } catch (e) {
    showToast(`Error saving ${key}`, 'error');
  }
}

// --- Stats ---
async function loadStats() {
  if (!currentGuildId) return;
  try {
    const resp = await fetch(`/api/stats/${currentGuildId}`);
    const stats = await resp.json();
    document.getElementById('statLearned').textContent = stats.messages_learned || 0;
    document.getElementById('statSent').textContent = stats.messages_sent || 0;
  } catch (e) {
    console.error('Failed to load stats:', e);
  }
}

// --- Actions ---
async function executeAction(action) {
  if (!currentGuildId) {
    showToast('Select a server first!', 'error');
    return;
  }

  const confirmMessages = {
    'load_brain': 'Load starter brain into this server?',
    'reset_all_settings': 'Reset ALL settings to defaults?',
    'reset_data': 'NUKE all learned data and settings? This cannot be undone!',
  };
  if (!confirm(confirmMessages[action])) return;

  try {
    const resp = await fetch(`/api/action/${currentGuildId}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action }),
    });
    const data = await resp.json();
    if (data.status === 'success') {
      if (action === 'load_brain') {
        showToast(`Brain loaded! ${data.lines_learned} lines learned.`, 'success');
      } else if (action === 'reset_all_settings') {
        showToast('Settings reset to defaults.', 'success');
        loadSettings();
      } else if (action === 'reset_data') {
        showToast('All data has been nuked.', 'success');
        loadSettings();
      }
      loadStats();
    }
  } catch (e) {
    showToast(`Action failed: ${e.message}`, 'error');
  }
}

// --- Init ---
async function init() {
  await fetchBotStatus();
  await fetchGuilds();
  // Auto-select first guild if only one
  const select = document.getElementById('guildSelect');
  if (select.options.length === 2) {
    select.selectedIndex = 1;
    onGuildChange();
  }
  // Refresh status periodically
  setInterval(fetchBotStatus, 30000);
}

init();
</script>
</body>
</html>
"""

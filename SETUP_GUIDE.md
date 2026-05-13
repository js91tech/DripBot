# Z.ai Hybrid Integration Setup Guide

## What Changed

Only **4 files** were modified from your original v5.5:

| File | Change |
|------|--------|
| `llm.py` | Added Z.ai sidecar client functions (vision, image gen, web search). OpenRouter chat is UNCHANGED. |
| `cogs/chat.py` | Added `_get_image_context()` (vision) and `_enrich_with_search()` (web search) methods. |
| `config/default_settings.py` | Added 3 new settings: `vision_enabled`, `web_search_enabled`, `zai_image_gen_enabled`. |
| `bot.py` | Added sidecar auto-start and health check on bot startup. |

## New Files

| File | Purpose |
|------|---------|
| `zai-sidecar/package.json` | Node.js dependencies |
| `zai-sidecar/server.js` | Express API that wraps Z.ai SDK |

## Setup Steps

### 1. Install Node.js Dependencies
```bash
cd zai-sidecar
npm install
cd ..
```

### 2. Set Environment Variable (Z.ai API Key)
```bash
export ZAI_API_KEY="your-zai-api-key-here"
```
Or add it to your `.env` / Render environment variables.

### 3. Deploy / Run
Everything else is the same! When your bot starts:
- `bot.py` auto-launches the Node.js sidecar
- It health-checks after 3 seconds
- If sidecar is up: vision, web search, and image gen are enabled
- If sidecar fails: bot works normally WITHOUT Z.ai features (graceful fallback)

### 4. That's it!
No other code changes needed. Your OpenRouter chat, Markov chains, memory system,
dashboard, and all existing features remain untouched.

## How It Works

```
User sends image in Discord
        |
        v
chat.py: _get_image_context()
        |
        v
llm.py: analyze_image_vision()  -->  HTTP POST to localhost:3456/vision
        |
        v
zai-sidecar/server.js  -->  z-ai-web-dev-sdk  -->  Z.ai API
        |
        v
Description injected into LLM prompt context
```

## Feature Priority (Image Generation)

1. **Z.ai sidecar** (free tier, good quality)
2. **OpenRouter** (your credits, GPT-4o etc)
3. **Pollinations.ai** (free, no key needed)

## New Dashboard Settings

Add these to your dashboard UI if you want toggles:

- `vision_enabled` (bool) - Analyze images sent in chat
- `web_search_enabled` (bool) - Enrich responses with web context
- `zai_image_gen_enabled` (bool) - Use Z.ai for image generation

## Troubleshooting

**"node_modules not found"**
```bash
cd zai-sidecar && npm install
```

**Sidecar starts but health check fails**
- Check the sidecar port isn't blocked: `curl http://127.0.0.1:3456/health`
- Make sure ZAI_API_KEY is set

**Bot works fine but no vision/search**
- This is expected if sidecar is down. Bot gracefully degrades.

**On Render:**
- Make sure Node.js buildpack is available (Render supports this natively)
- The sidecar starts as a subprocess of your Python bot

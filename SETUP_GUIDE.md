# Z.ai Hybrid Integration Setup Guide

## Overview

The bot uses the Python sidecar in `zai_sidecar.py` for optional Z.ai features:
vision, web search, and image generation. Node.js is not required.

## Setup

1. Install Python dependencies:
   ```bash
   pip install -r requirements.txt
   ```
2. Set the optional Z.ai API key if you want sidecar features:
   ```bash
   export ZAI_API_KEY="your-zai-api-key-here"
   ```
3. Start the bot:
   ```bash
   python3 bot.py
   ```

When `zai_sidecar.py` is present, `bot.py` starts it as a managed subprocess.
If the sidecar fails to start, the bot continues running and LLM/Markov features
remain available.

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
zai_sidecar.py  -->  Z.ai API
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

**Sidecar starts but health check fails**
- Check the sidecar port isn't blocked: `curl http://127.0.0.1:3456/health`
- Make sure ZAI_API_KEY is set

**Bot works fine but no vision/search**
- This is expected if sidecar is down. Bot gracefully degrades.

**On Render:**
- Build command: `pip install -r requirements.txt`
- Start command: `python bot.py`
- The sidecar starts as a subprocess of your Python bot

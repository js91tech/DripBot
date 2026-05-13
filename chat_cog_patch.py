"""
chat_cog_patch.py — Changes for cogs/chat.py

Replace the chat message handler's LLM call section with this logic.
This adds auto-router support, vision analysis, and web search enrichment.

Find your on_message handler where it calls llm_handler.chat() and
replace that section with the code below.
"""

# ═══════════════════════════════════════════════════════════════
#  Inside your on_message handler, after building the messages list:
# ═══════════════════════════════════════════════════════════════

# --- Vision: check for image attachments ---
if message.attachments:
    for attachment in message.attachments:
        if attachment.filename and attachment.filename.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.webp')):
            if settings.get("vision_enabled", False):
                try:
                    description = await llm_handler.analyze_image(
                        image_url=attachment.url,
                        prompt="Describe this image in detail for context."
                    )
                    if description:
                        messages.append({
                            "role": "user",
                            "content": f"[Image attached: {attachment.filename}]\nImage description: {description}"
                        })
                except Exception as e:
                    print(f"[Vision] Error analyzing image: {e}")

# --- Web Search: enrich context if enabled ---
if settings.get("web_search_enabled", False):
    try:
        search_results = await llm_handler.web_search(message.content[:100], num=3)
        if search_results:
            context = "\n".join([
                f"- {r.get('name', 'Untitled')}: {r.get('snippet', '')[:150]}"
                for r in search_results
            ])
            messages.insert(0, {
                "role": "system",
                "content": f"Web search context (use if relevant):\n{context}"
            })
    except Exception as e:
        print(f"[Search] Error: {e}")

# --- Get system prompt ---
personality = settings.get("personality", {})
system_prompt = personality.get("system_prompt", "")

# --- Chat call with Auto Router ---
auto_router = settings.get("auto_router_enabled", False)
allowed_models = settings.get("auto_router_allowed_models", [])
model = settings.get("model", "meta-llama/llama-4-maverick:free")

result = await llm_handler.chat(
    messages,
    model=model,
    system_prompt=system_prompt,
    auto_router=auto_router,
    allowed_models=allowed_models if allowed_models else None,
)

if result and result.get("content"):
    response_text = result["content"]
    model_used = result.get("model_used", model)
    
    # Optionally log which model was used
    if auto_router:
        print(f"[AutoRouter] Selected model: {model_used}")
    
    await message.reply(response_text)
else:
    # Fallback to Markov or default response
    pass  # ... your existing fallback logic

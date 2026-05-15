import os
import io
import base64
import discord
from discord.ext import commands, tasks
import random
import time
import re
from collections import deque
from datetime import timedelta, datetime, timezone
from config.default_settings import HANNAH_PROMPT
from utils import sanitize_message, search_gif
from llm import generate_llm_response, generate_image, analyze_image_vision, web_search_zai

FALLBACK_QUOTES = [
    "what",
    "no lmfao",
    "ain't no way",
    "that's crazy",
    "idk what u mean",
    "hell nah",
    "are you fr",
    "my b",
    "sigh",
    "english",
    "not my problem",
    "why would you say that",
    "ur weird",
    "i'm confused",
    "dunno what you mean",
]

IMAGE_TRIGGER_WORDS = [
    "imagine", "generate image", "create image", "make image",
    "draw", "paint", "illustrate", "render image",
    "generate a picture", "create a picture", "make a picture",
    "generate art", "create art", "make art",
    "text to image", "txt2img", "t2i",
]

IMAGE_FALSE_POSITIVES = [
    "imagine that", "imagine if", "i can imagine", "just imagine",
    "imagine being", "imagine having", "hard to imagine", "imagine this",
    "imagine a world", "i imagine", "you imagine", "we imagine",
]

FUZZY_DEDUP_THRESHOLD = 0.70
FUZZY_DEDUP_WINDOW = 8
MIN_REPLY_COOLDOWN_SECONDS = 5
MAX_REPLY_CHARS = 200

RESPONSE_STYLE_PROMPT = (
    "GLOBAL REPLY STYLE: Reply like Discord chat — short, casual, reactive. "
    "One or two tiny lines max. Fragments are fine. No paragraphs or assistant voice."
)


class Chat(commands.Cog):
    def __init__(self, bot, db, settings_manager):
        self.bot = bot
        self.db = db
        self.settings_manager = settings_manager
        self.channel_counters = {}
        self.channel_cooldowns = {}
        self.bot_recent_messages = {}
        self.last_bot_engagement = {}
        self.recent_timestamps = {}
        self.channel_message_goals = {}

    async def cog_load(self):
        self.proactive_loop.start()
        self.memory_consolidation_loop.start()

    async def cog_unload(self):
        self.proactive_loop.cancel()
        self.memory_consolidation_loop.cancel()

    def _personality_prompt(self, settings):
        return settings.get("personality_prompt") or HANNAH_PROMPT

    def _is_fuzzy_duplicate(self, text, guild_id):
        text_words = set(text.lower().split())
        if len(text_words) < 3:
            return False
        recent = self.bot_recent_messages.get(guild_id, [])
        recent_window = recent[-FUZZY_DEDUP_WINDOW:]
        for past_msg in recent_window:
            past_words = set(past_msg.lower().split())
            if len(past_words) < 3:
                continue
            overlap = len(text_words & past_words) / len(text_words | past_words)
            if overlap >= FUZZY_DEDUP_THRESHOLD:
                return True
        return False

    def _effective_cooldown_seconds(self, settings):
        try:
            configured = float(settings.get("cooldown_seconds", MIN_REPLY_COOLDOWN_SECONDS))
        except (TypeError, ValueError):
            configured = MIN_REPLY_COOLDOWN_SECONDS
        return max(MIN_REPLY_COOLDOWN_SECONDS, configured)

    def _cooldown_active(self, channel_id, settings):
        last_reply_at = self.channel_cooldowns.get(channel_id)
        if last_reply_at is None:
            return False
        return time.time() - last_reply_at < self._effective_cooldown_seconds(settings)

    def _trim_reply(self, text):
        """Keep LLM output in the casual 1-2 sentence shape requested for chat."""
        if not text:
            return text

        lines = [line.strip() for line in text.splitlines() if line.strip()]
        text = " ".join(lines[:2]) if lines else text.strip()

        sentences = re.split(r'(?<=[.!?])\s+', text)
        if len(sentences) > 2:
            text = " ".join(sentences[:2]).strip()

        if len(text) > MAX_REPLY_CHARS:
            shortened = text[:MAX_REPLY_CHARS].rsplit(" ", 1)[0].strip()
            text = shortened or text[:MAX_REPLY_CHARS].strip()

        return text

    def _is_image_request(self, message_content):
        clean = re.sub(r'<@!?\d+>', '', message_content).strip()
        clean_lower = clean.lower().strip()
        for fp in IMAGE_FALSE_POSITIVES:
            if fp in clean_lower:
                return None
        is_image = False
        for trigger in IMAGE_TRIGGER_WORDS:
            if trigger in clean_lower:
                is_image = True
                break
        if not is_image:
            return None
        remaining = clean_lower
        for trigger in IMAGE_TRIGGER_WORDS:
            remaining = remaining.replace(trigger, "").strip()
        filler_words = ["a", "an", "the", "of", "for", "me", "please", "can", "you",
                        "could", "would", "something", "some", "this", "that"]
        remaining_words = [w for w in remaining.split() if w not in filler_words]
        if len(remaining_words) < 2:
            return None
        return clean

    # Vision - analyze image attachments
    async def _get_image_context(self, message):
        if not message.attachments:
            return None
        settings = await self.settings_manager.get_settings(message.guild.id)
        if not settings.get("vision_enabled", True):
            return None
        image_urls = []
        for att in message.attachments:
            if att.content_type and "image" in att.content_type:
                image_urls.append(att.url)
        if not image_urls:
            return None
        try:
            description = await analyze_image_vision(
                image_urls[0],
                prompt="Briefly describe what's in this image in 1-2 sentences. Focus on the main subject."
            )
            if description:
                print(f"[VISION] Analyzed image: {description[:80]}...")
                return description
        except Exception as e:
            print(f"[VISION] Error analyzing image: {e}")
        return None

    # Web Search - takes message object (not string)
    async def _enrich_with_search(self, message):
        settings = await self.settings_manager.get_settings(message.guild.id)
        if not settings.get("web_search_enabled", True):
            return None
        search_keywords = [
            "what is", "who is", "when was", "where is", "how much",
            "latest", "current", "today", "news", "price of",
            "define", "meaning of", "explain",
        ]
        msg_lower = message.content.lower()
        if not any(kw in msg_lower for kw in search_keywords):
            return None
        clean = re.sub(r'<@!?\d+>', '', message.content).strip()
        query = re.sub(r'^(can you|could you|what is|who is|when was|where is|how much|tell me about|explain)\s*', '', clean, flags=re.IGNORECASE).strip()
        query = query.rstrip('?!.').strip()
        if len(query) < 3:
            return None
        try:
            results = await web_search_zai(query, num=3)
            if results:
                snippets = [f"- {r['snippet']}" for r in results[:2] if r.get('snippet')]
                if snippets:
                    context = f"[Web context: {' '.join(snippets)}]"
                    print(f"[SEARCH] Found context for: {query[:50]}...")
                    return context
        except Exception as e:
            print(f"[SEARCH] Error: {e}")
        return None

    # Proactive loop
    @tasks.loop(minutes=90)
    async def proactive_loop(self):
        await self.bot.wait_until_ready()
        for guild in self.bot.guilds:
            if random.random() > 0.16:
                continue
            settings = await self.settings_manager.get_settings(guild.id)
            if not settings.get("proactive_enabled", False) or not settings.get("response_enabled"):
                continue
            target_channel = None
            allowed = settings.get("allowed_channels", [])
            if allowed:
                target_channel = guild.get_channel(random.choice(allowed))
            else:
                text_channels = [c for c in guild.text_channels if c.permissions_for(guild.me).send_messages]
                if text_channels:
                    target_channel = random.choice(text_channels)
            if not target_channel:
                continue
            try:
                last_msgs = [m async for m in target_channel.history(limit=1)]
                if not last_msgs or (datetime.now(timezone.utc) - last_msgs[0].created_at).total_seconds() > 7200:
                    continue
            except Exception:
                continue
            chat_history = []
            async for msg in target_channel.history(limit=50):
                if msg.content.startswith("/") and not msg.attachments:
                    continue
                clean_msg_content = re.sub(r'<@!?\d+>', '', msg.content).strip()
                if msg.author == self.bot.user:
                    chat_history.insert(0, {"role": "assistant", "content": clean_msg_content})
                else:
                    chat_history.insert(0, {"role": "user", "content": f"{msg.author.display_name}: {clean_msg_content}"})
            if len(chat_history) < 10:
                continue
            prompt = (
                "You just walked into the room and saw this conversation. "
                "You don't need to reply directly, but if a random thought "
                "pops into your head, say it. If nothing, say NO_THOUGHT. "
                + RESPONSE_STYLE_PROMPT
            )
            chat_history.insert(0, {"role": "system", "content": prompt,
                                "model": settings.get("llm_model", "meta-llama/llama-4-maverick:free")})
            response = await generate_llm_response(prompt, chat_history)
            if response and "NO_THOUGHT" not in response.upper():
                response = re.sub(r'^.{0,30}?:\s*', '', response).strip()
                response = re.sub(r'<@!?\d+>', '', response).strip()
                response = self._trim_reply(response)
                try:
                    await target_channel.send(sanitize_message(response))
                except Exception:
                    pass

    @tasks.loop(hours=24)
    async def memory_consolidation_loop(self):
        await self.bot.wait_until_ready()
        for guild in self.bot.guilds:
            settings = await self.settings_manager.get_settings(guild.id)
            target_channel = None
            allowed = settings.get("allowed_channels", [])
            if allowed:
                target_channel = guild.get_channel(allowed[0])
            else:
                text_channels = [c for c in guild.text_channels if c.permissions_for(guild.me).read_message_history]
                if text_channels:
                    target_channel = text_channels[0]
            if not target_channel:
                continue
            chat_history = []
            async for msg in target_channel.history(limit=500):
                if msg.content.startswith("/"):
                    continue
                clean_msg_content = re.sub(r'<@!?\d+>', '', msg.content).strip()
                if msg.author == self.bot.user:
                    chat_history.insert(0, {"role": "assistant", "content": clean_msg_content})
                else:
                    chat_history.insert(0, {"role": "user", "content": f"{msg.author.display_name}: {clean_msg_content}"})
            if len(chat_history) < 50:
                continue
            prompt = (
                "You are a memory archiver for a Discord bot. Summarize the "
                "inside jokes, drama, key facts, and user dynamics from this "
                "chat log. Keep it under 500 words."
            )
            chat_history.insert(0, {"role": "system", "content": prompt,
                                "model": settings.get("llm_model", "meta-llama/llama-4-maverick:free")})
            summary = await generate_llm_response(prompt, chat_history)
            if summary:
                await self.db.save_consolidated_memory(guild.id, {"summary": summary, "timestamp": time.time()})

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if isinstance(message.channel, discord.DMChannel):
            owner_id = int(os.getenv("OWNER_USER_ID", "0"))
            if owner_id != 0 and message.author.id == owner_id and message.content:
                target_channel_id = int(os.getenv("OWNER_TARGET_CHANNEL_ID", "0"))
                if target_channel_id != 0:
                    target_channel = self.bot.get_channel(target_channel_id)
                    puppet_enabled = True
                    if target_channel and getattr(target_channel, "guild", None):
                        puppet_settings = await self.settings_manager.get_settings(
                            target_channel.guild.id
                        )
                        puppet_enabled = puppet_settings.get("puppet_enabled", True)
                    if not puppet_enabled:
                        return
                    if target_channel:
                        try:
                            await target_channel.send(message.content)
                            await message.author.send("Spoke in server.")
                        except discord.errors.HTTPException as e:
                            await message.author.send(f"Failed to send: {e}")
                    else:
                        await message.author.send("Target channel not found.")
            return

        if message.guild is None or message.author == self.bot.user:
            return

        guild_id = message.guild.id
        channel_id = message.channel.id
        settings = await self.settings_manager.get_settings(guild_id)

        if channel_id in settings["ignored_channels"]:
            return
        if settings["allowed_channels"] and channel_id not in settings["allowed_channels"]:
            return
        if message.author.id in settings["ignored_users"]:
            return

        is_bot = message.author.bot
        if is_bot and not settings["learn_from_bots"]:
            return

        if is_bot or message.content.startswith("/"):
            return
        if not settings["response_enabled"]:
            return

        # IMAGE GENERATION CHECK
        # FIX v5.8: Image gen now fires on ANY message (not just mention/reply)
        # when the trigger words are detected. The old code required mention/reply
        # which made it almost impossible to trigger naturally.
        image_prompt = self._is_image_request(message.content)
        if image_prompt:
            # Check cooldown
            skip_image = False
            if self._cooldown_active(channel_id, settings):
                skip_image = True

            if not skip_image:
                # Only require mention/reply for image gen if zai_image_gen_enabled is on
                # (prevents random users from burning API credits)
                # If image_model is "pollinations" (free), allow without mention
                image_model = settings.get("image_model", "zai-sidecar")
                requires_mention = image_model != "pollinations"

                if requires_mention and not is_mentioned_or_replied(self.bot.user, message, settings):
                    image_prompt = None  # Skip — not mentioned
                else:
                    print(f"[IMAGE] Generating image with model={image_model}, prompt=\"{image_prompt[:80]}\"")
                    try:
                        async with message.channel.typing():
                            image_url = await generate_image(image_prompt, model_name=image_model)
                        if image_url:
                            if image_url.startswith("data:image/"):
                                header, encoded = image_url.split(",", 1)
                                ext = header.split("/")[1].split(";")[0]
                                img_data = base64.b64decode(encoded)
                                img_file = discord.File(io.BytesIO(img_data), f"image.{ext}")
                                await message.channel.send(file=img_file, reference=message)
                            else:
                                await message.channel.send(image_url, reference=message)
                            self.channel_cooldowns[channel_id] = time.time()
                            await self.db.increment_stat(guild_id, "messages_sent")
                            if guild_id not in self.bot_recent_messages:
                                self.bot_recent_messages[guild_id] = []
                            self.bot_recent_messages[guild_id].append(f"[IMAGE] {image_prompt[:50]}")
                            self.bot_recent_messages[guild_id] = self.bot_recent_messages[guild_id][-20:]
                            print("[IMAGE] Successfully sent image")
                            return
                        else:
                            print(f"[IMAGE] generate_image() returned None for model={image_model}")
                    except Exception as e:
                        print(f"[IMAGE] Exception during generation: {e}")
                    image_prompt = None

        # MESSAGE COUNTING
        if channel_id not in self.channel_counters:
            self.channel_counters[channel_id] = 0
        self.channel_counters[channel_id] += 1
        if channel_id not in self.channel_message_goals:
            self.channel_message_goals[channel_id] = random.randint(4, 10)
        if channel_id not in self.recent_timestamps:
            self.recent_timestamps[channel_id] = deque(maxlen=50)
        self.recent_timestamps[channel_id].append(time.time())

        # TRIGGER LOGIC
        should_respond = False
        is_mentioned = self.bot.user.mentioned_in(message)
        is_reply_to_bot = (message.reference and message.reference.resolved and
                           message.reference.resolved.author == self.bot.user)

        if is_mentioned and settings["trigger_on_mention"]:
            should_respond = True
        elif is_reply_to_bot and settings["trigger_on_reply"]:
            should_respond = True

        # Check response_chance for non-direct triggers
        if not should_respond:
            window_seconds = settings.get("conversation_window_seconds", 120)
            indirect_chance = settings.get("indirect_reply_chance", 0.40)
            engagement = self.last_bot_engagement.get(channel_id)
            if engagement and time.time() - engagement["time"] < window_seconds:
                chance = indirect_chance
                if message.author.id == engagement["user_id"]:
                    chance = indirect_chance * 2.0
                if random.random() < chance:
                    should_respond = True

        # response_chance gates count-based triggers
        if not should_respond:
            response_chance = settings.get("response_chance", 0.15)
            if random.random() < response_chance:
                if self.channel_counters[channel_id] >= self.channel_message_goals[channel_id]:
                    should_respond = True

        if should_respond:
            if self._cooldown_active(channel_id, settings):
                should_respond = False

        # EXECUTE RESPONSE
        if should_respond:
            if random.random() < settings["reaction_chance"]:
                emoji_options = ['💀', '😭', '🔥', '💯', '🤣', '🙄', '👀', '🫡', '🤨']
                try:
                    await message.add_reaction(random.choice(emoji_options))
                    self.channel_cooldowns[channel_id] = time.time()
                    self.channel_counters[channel_id] = 0
                    self.channel_message_goals[channel_id] = random.randint(4, 10)
                    return
                except discord.errors.HTTPException:
                    pass

            async with message.channel.typing():
                image_description = await self._get_image_context(message)
                web_context = await self._enrich_with_search(message)

                use_reply = is_mentioned or is_reply_to_bot or (random.random() < settings["random_reply_chance"])
                use_mention = (random.random() < settings["random_mention_chance"])
                use_gif = (random.random() < settings["gif_chance"])
                final_content = None
                reference = message if use_reply else None

                if not use_gif:
                    chat_history = []
                    prev_msg_time = None
                    async for msg in message.channel.history(limit=100):
                        if msg.id == message.id:
                            continue
                        if msg.content.startswith("/") and not msg.attachments:
                            continue
                        if prev_msg_time:
                            time_diff = prev_msg_time - msg.created_at
                            if time_diff > timedelta(minutes=30):
                                chat_history.insert(0, {"role": "system", "content": "--- A long time passes ---"})
                        prev_msg_time = msg.created_at
                        clean_msg_content = re.sub(r'<@!?\d+>', '', msg.content).strip()
                        clean_msg_content = re.sub(r'<#\d+>', '', clean_msg_content).strip()
                        if msg.author == self.bot.user:
                            role = "assistant"
                            content_payload = clean_msg_content
                        else:
                            role = "user"
                            content_payload = []
                            text_part = f"{msg.author.display_name}: {clean_msg_content if clean_msg_content else 'sent an image'}"
                            content_payload.append({"type": "text", "text": text_part})
                            for att in msg.attachments:
                                if att.content_type and "image" in att.content_type:
                                    content_payload.append({"type": "image_url", "image_url": {"url": att.url}})
                            if not clean_msg_content and not msg.attachments:
                                continue
                        chat_history.insert(0, {"role": role, "content": content_payload})

                    clean_trigger_content = re.sub(r'<@!?\d+>', '', message.content).strip()
                    trigger_payload = []
                    trigger_text = f"{message.author.display_name}: {clean_trigger_content if clean_trigger_content else 'sent an image'}"

                    if image_description:
                        trigger_text += f" [The user sent an image: {image_description}]"
                    if web_context:
                        trigger_text += f" {web_context}"

                    trigger_payload.append({"type": "text", "text": trigger_text})
                    for att in message.attachments:
                        if att.content_type and "image" in att.content_type:
                            trigger_payload.append({"type": "image_url", "image_url": {"url": att.url}})
                    chat_history.append({"role": "user", "content": trigger_payload})

                    user_memories = []
                    consolidated = None
                    if settings.get("memory_enabled", True):
                        user_memories = await self.db.get_memories(guild_id, message.author.id)
                        consolidated = await self.db.get_consolidated_memory(guild_id)

                    dynamic_prompt = self._personality_prompt(settings)
                    dynamic_prompt += f"\n\n{RESPONSE_STYLE_PROMPT}"
                    if consolidated and consolidated.get("summary"):
                        dynamic_prompt += f"\n\nCONTEXT OF SERVER CULTURE:\n{consolidated['summary']}\nUse this subtly."
                    if user_memories:
                        memory_str = "\n".join([f"- {m}" for m in user_memories])
                        dynamic_prompt += (
                            f"\n\nPermanent memories about {message.author.display_name}:\n{memory_str}\n"
                            "Reference these casually when relevant."
                        )

                    chat_history.insert(0, {"role": "system", "content": dynamic_prompt,
                                        "model": settings.get("llm_model", "meta-llama/llama-4-maverick:free")})

                    llm_response = await generate_llm_response(dynamic_prompt, chat_history)
                    if llm_response:
                        llm_response = re.sub(r'^.{0,30}?:\s*', '', llm_response).strip()
                        llm_response = re.sub(r'<@!?\d+>', '', llm_response).strip()
                        if self._is_fuzzy_duplicate(llm_response, guild_id):
                            print("[DEDUP] Blocked fuzzy duplicate response")
                            llm_response = None
                        if llm_response:
                            base_text = sanitize_message(llm_response)
                            final_content = f"{message.author.mention} {base_text}" if use_mention else base_text
                            if guild_id not in self.bot_recent_messages:
                                self.bot_recent_messages[guild_id] = []
                            self.bot_recent_messages[guild_id].append(llm_response.lower().strip())
                            self.bot_recent_messages[guild_id] = self.bot_recent_messages[guild_id][-20:]
                        else:
                            final_content = None
                    else:
                        print(f"[{guild_id}] LLM returned None.")

                    if not final_content:
                        final_content = random.choice(FALLBACK_QUOTES)

                elif use_gif:
                    search_words = [w for w in message.content.lower().split() if len(w) > 3]
                    search_query = random.choice(search_words) if search_words else "meme"
                    gif_url = await search_gif(search_query)
                    if gif_url:
                        final_content = f"{message.author.mention} " if use_mention else ""
                        final_content += gif_url
                    else:
                        final_content = random.choice(FALLBACK_QUOTES)

                if final_content:
                    if not use_gif:
                        final_content = self._trim_reply(final_content)
                    try:
                        await message.channel.send(final_content, reference=reference)
                        self.channel_cooldowns[channel_id] = time.time()
                        await self.db.increment_stat(guild_id, "messages_sent")
                        self.last_bot_engagement[channel_id] = {"time": time.time(), "user_id": message.author.id}
                        self.channel_counters[channel_id] = 0
                        self.channel_message_goals[channel_id] = random.randint(4, 10)
                    except discord.errors.HTTPException as e:
                        print(f"[{guild_id}] Error sending message: {e}")


def is_mentioned_or_replied(bot_user, message, settings):
    is_mentioned = bot_user.mentioned_in(message)
    is_reply_to_bot = (message.reference and message.reference.resolved and
                       message.reference.resolved.author == bot_user)
    return (is_mentioned and settings.get("trigger_on_mention")) or \
           (is_reply_to_bot and settings.get("trigger_on_reply"))


async def setup(bot):
    await bot.add_cog(Chat(bot, bot.db, bot.settings_manager))

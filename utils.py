import aiohttp
import html
import re
import time
from datetime import datetime, timezone

# Cached Google Trends titles. Refreshed at most every 6 hours so we
# do not spend tokens or HTTP on every Discord message.
_TRENDS_TTL_SECONDS = 6 * 60 * 60
_MAX_TRENDS = 5
_trends_cache = {"topics": [], "fetched_at": 0.0}

_TRENDS_FEEDS = (
    "https://trends.google.com/trending/rss?geo=US",
    "https://trends.google.com/trends/trendingsearches/daily/rss?geo=US",
)


def current_date_label(now=None):
    """Short human date the model can use without a long clock dump."""
    now = now or datetime.now(timezone.utc)
    return now.strftime("%A, %b %d, %Y")


def _is_usable_trend(title):
    """Skip non-Latin filler titles so the prompt stays short and readable."""
    letters = [c for c in title if c.isalpha()]
    if not letters:
        return False
    latin = sum(1 for c in letters if "A" <= c.upper() <= "Z")
    return latin / len(letters) >= 0.6


def _parse_rss_titles(xml_text):
    raw_titles = []
    for raw in re.findall(r"<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>", xml_text, flags=re.DOTALL | re.IGNORECASE):
        title = html.unescape(re.sub(r"\s+", " ", raw).strip())[:60]
        if title:
            raw_titles.append(title)
    # First <title> is the feed name, not a trend.
    titles = []
    seen = set()
    for title in raw_titles[1:]:
        key = title.lower()
        if key in seen or not _is_usable_trend(title):
            continue
        seen.add(key)
        titles.append(title)
    return titles


async def get_trending_topics():
    """Return a few cached US Google Trends titles (empty list on failure)."""
    now = time.time()
    if _trends_cache["topics"] and now - _trends_cache["fetched_at"] < _TRENDS_TTL_SECONDS:
        return list(_trends_cache["topics"])

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (compatible; Dripsletongue/5.8; +https://github.com/dripsletongue)"
        )
    }
    topics = []
    try:
        timeout = aiohttp.ClientTimeout(total=8)
        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            for url in _TRENDS_FEEDS:
                try:
                    async with session.get(url) as resp:
                        if resp.status != 200:
                            continue
                        topics = _parse_rss_titles(await resp.text())[:_MAX_TRENDS]
                        if topics:
                            break
                except Exception:
                    continue
    except Exception as e:
        print(f"Trends fetch error: {e}")

    if topics:
        _trends_cache["topics"] = topics
        _trends_cache["fetched_at"] = now
        return list(topics)

    # Keep stale titles if a refresh failed so the bot still has some context.
    return list(_trends_cache["topics"])


async def world_context_line():
    """Tiny prompt add-on: today's date plus a handful of trend names."""
    date_label = current_date_label()
    topics = await get_trending_topics()
    if topics:
        return (
            f"Today is {date_label} (UTC). Trending: {', '.join(topics)}. "
            "Use only if someone asks about the date, news, or a related topic."
        )
    return (
        f"Today is {date_label} (UTC). "
        "Use only if someone asks about the date or current events."
    )


async def search_gif(query):
    """Searches Tenor directly for a random GIF without needing an API key."""
    url = f"https://tenor.com/search/{query}-gifs"
    try:
        async with aiohttp.ClientSession() as session:
            # We add headers so Tenor thinks it's a normal web browser
            headers = {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/91.0.4472.124 Safari/537.36"
                )
            }
            async with session.get(url, headers=headers) as resp:
                if resp.status == 200:
                    text = await resp.text()
                    # Use regex to find all Tenor GIF URLs in the page source
                    gif_urls = re.findall(r'https://media\.tenor\.com/[^"\s]+\.gif', text)
                    if gif_urls:
                        import random
                        return random.choice(gif_urls)
    except Exception as e:
        print(f"GIF Search Error: {e}")
    return None


def engaged_with_other_user(engagement, author_id, now, window_seconds):
    """True if the bot is mid-conversation with someone else in this channel."""
    if not engagement or not author_id:
        return False
    try:
        elapsed = now - float(engagement.get("time", 0))
        other_id = int(engagement.get("user_id", 0))
    except (TypeError, ValueError):
        return False
    return elapsed < window_seconds and other_id not in (0, int(author_id))


def format_speaker_line(author_name, content, reply_to=None):
    """One history line so the model can tell who spoke and who they replied to."""
    body = content if content else "sent an image"
    if reply_to:
        return f"{author_name} (replying to {reply_to}): {body}"
    return f"{author_name}: {body}"


def addressee_instruction(display_name):
    """Tiny prompt pin: answer this person, not someone else in the log."""
    name = (display_name or "them").strip() or "them"
    return (
        f"You are talking to {name} only. Reply to their latest message, not someone else's. "
        "Do not start with a name, username, or @."
    )


def strip_leading_address(text, names=None):
    """Drop leftover 'Name:' / '@Name' prefixes so the Discord reply target stays correct."""
    if not text:
        return text
    cleaned = text.strip()
    cleaned = re.sub(r"^<@!?\d+>\s*", "", cleaned)
    cleaned = re.sub(r"^@\S+[,:\s]+", "", cleaned)
    for name in sorted({n for n in (names or []) if n and len(n) >= 2}, key=len, reverse=True):
        cleaned = re.sub(
            rf"^@?{re.escape(name)}\s*[:,\-–]\s*",
            "",
            cleaned,
            flags=re.IGNORECASE,
        )
    # Only peel a short name label ("Alex:" / "Dr Umar:"). A blanket
    # "anything before the first colon" strip was deleting real sentences
    # such as "Here's the practical problem: rent went up."
    name_label = re.match(
        r"^(@?[A-Za-z0-9_][A-Za-z0-9_'\-]{0,24}"
        r"(?:\s+[A-Za-z0-9_][A-Za-z0-9_'\-]{0,24}){0,2})\s*:\s*",
        cleaned,
    )
    if name_label:
        cleaned = cleaned[name_label.end():].strip()
    cleaned = re.sub(r"<@!?\d+>", "", cleaned).strip()
    return cleaned


def sanitize_message(text):
    """Cleans up bot messages to prevent Discord API errors."""
    if not text:
        return ""
    text = str(text)
    # Remove @everyone and @here to prevent mass pings
    text = text.replace("@everyone", "").replace("@here", "")
    # Remove duplicate whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    # Discord messages have a 2000 character limit
    if len(text) > 1950:
        text = text[:1950] + "..."
    return text


_LOW_SIGNAL_MESSAGES = {
    "ok", "okay", "k", "kk", "lol", "lmao", "lmfao", "haha", "hahaha",
    "yes", "yeah", "yep", "nah", "no", "np", "ty", "thx", "thanks",
    "gn", "gm", "night", "bye", "same", "true", "fr", "real", "bet",
    "mood", "bruh", "damn", "omg", "ikr", "idk", "oh", "ah", "mhm",
}



def is_low_signal_message(text: str) -> bool:
    """True for tiny reactions that usually should not start a new bot turn."""
    if not text:
        return True
    cleaned = re.sub(r"<@!?\d+>", "", text)
    cleaned = re.sub(r"https?://\S+", "", cleaned)
    cleaned = re.sub(r"[^a-zA-Z0-9\s']", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip().lower()
    if not cleaned:
        return True
    if len(cleaned) <= 2:
        return True
    return cleaned in _LOW_SIGNAL_MESSAGES


def looks_like_fact_question(text: str) -> bool:
    """True when the user seems to want an outside fact, not just chat."""
    if not text or len(text.strip()) < 4:
        return False
    cleaned = re.sub(r"<@!?\d+>", "", text).strip()
    lower = cleaned.lower()
    conversational = re.search(
        r"\b(what are you|what'?s up|how are you|what do you|why are you|where are you|who are you|how'?s it going)\b",
        lower,
    )
    if conversational:
        return False
    factual_cues = re.search(
        r"\b("
        r"who won|who lost|what is|what was|what are(?! you)|what'?s(?! up)|"
        r"when is|when was|where is|where was|"
        r"how much|how many|how long|how old|"
        r"score|news|latest|today|tonight|current|price of|define|meaning of|explain|look up|search|"
        r"did .+ (win|lose|happen)"
        r")\b",
        lower,
    )
    if not factual_cues:
        return False
    # Prefer clear question-shaped asks.
    if cleaned.endswith("?") or factual_cues:
        return len(cleaned.split()) >= 3
    return False


def message_mentions_image_context(text: str) -> bool:
    """True when the text is actually about an attached/linked image."""
    if not text:
        return False
    return bool(re.search(
        r"\b(this|that|img|image|pic|picture|photo|screenshot|meme|look(?: at)? this)\b",
        text,
        re.I,
    ))


# Conversational "draw/imagine/paint" requests. Longer phrases first so
# "generate a picture" wins over leftover fragments.
IMAGE_FALSE_POSITIVES = (
    "imagine that", "imagine if", "i can imagine", "just imagine",
    "imagine being", "imagine having", "hard to imagine", "imagine this",
    "imagine a world", "i imagine", "you imagine", "we imagine",
)

_IMAGE_TRIGGER_RE = re.compile(
    r"(?:"
    r"generate\s+(?:me\s+)?(?:an?\s+)?(?:image|picture|pic|art)\s+(?:of\s+)?"
    r"|create\s+(?:me\s+)?(?:an?\s+)?(?:image|picture|pic|art)\s+(?:of\s+)?"
    r"|make\s+(?:me\s+)?(?:an?\s+)?(?:image|picture|pic|art)\s+(?:of\s+)?"
    r"|render\s+(?:an?\s+)?image\s+(?:of\s+)?"
    r"|text\s+to\s+image|txt2img|\bt2i\b"
    r"|\billustrate(?:\s+me)?"
    r"|\bpaint(?:\s+me)?"
    r"|\bdraw(?:\s+me)?"
    r"|\bimagine"
    r")\b",
    re.I,
)

_IMAGE_CHATTER_RE = re.compile(
    r"^(?:"
    r"hey+|hi+|yo+|sup|ok(?:ay)?|please|pls|plz|uhm+|um+|so|"
    r"(?:can|could|would|will)\s+you(?:\s+please|\s+pls|\s+plz)?"
    r"|i\s+(?:want|need)\s+you\s+to"
    r"|(?:wanna|want\s+to|gonna)"
    r")[\s,]+",
    re.I,
)

_IMAGE_FILLER_WORDS = {
    "a", "an", "the", "of", "for", "me", "please", "pls", "plz", "can", "you",
    "could", "would", "will", "something", "some", "this", "that", "hey",
    "hi", "yo", "ok", "okay", "to", "and", "just",
}

_DEFAULT_IMAGE_ADDRESS_NAMES = ("hannah", "hanah")
_SKIP_IMAGE_ADDRESS_NAMES = {
    "bot", "user", "discord", "app", "official", "the", "you", "her",
}


def default_image_address_names(*extra):
    """Names that are the bot being addressed, not the image subject."""
    names = set(_DEFAULT_IMAGE_ADDRESS_NAMES)
    for value in extra:
        text = str(value or "").strip().lower()
        if len(text) >= 3 and text not in _SKIP_IMAGE_ADDRESS_NAMES:
            names.add(text)
    return names


def _strip_leading_image_address(text, names):
    """Remove 'hannah,' / bot-name prefixes so they are not the image subject."""
    cleaned = (text or "").strip()
    if not cleaned:
        return cleaned
    name_list = sorted(
        {n.strip().lower() for n in (names or []) if n and len(str(n).strip()) >= 3},
        key=len,
        reverse=True,
    )
    changed = True
    while changed and cleaned:
        changed = False
        stripped = _IMAGE_CHATTER_RE.sub("", cleaned, count=1).strip()
        if stripped != cleaned:
            cleaned = stripped
            changed = True
            continue
        for name in name_list:
            match = re.match(rf"^{re.escape(name)}\b(?:[\s,.:;!\-]+|$)", cleaned, flags=re.I)
            if match and match.end() < len(cleaned):
                cleaned = cleaned[match.end():].strip()
                changed = True
                break
    return cleaned


def extract_image_prompt(message_content, address_names=None):
    """
    Turn a chat request into the visual subject only.

    'hannah can you draw me a red dragon' -> 'a red dragon'
    'draw hannah montana on stage' -> 'hannah montana on stage'
    Returns None when this is not an image request.
    """
    clean = re.sub(r"<@!?&?\d+>", "", message_content or "").strip()
    clean = re.sub(r"\s+", " ", clean)
    if not clean:
        return None

    lower = clean.lower()
    for false_positive in IMAGE_FALSE_POSITIVES:
        if false_positive in lower:
            return None

    names = default_image_address_names(*(address_names or []))
    working = _strip_leading_image_address(clean, names)
    match = _IMAGE_TRIGGER_RE.search(working)
    if not match:
        return None

    subject = working[match.end():].strip(" \t,.:;!-")
    # 'draw me a cat' already consumed 'me' in the trigger; still handle leftovers.
    subject = re.sub(r"^me\s+(?=(?:an?|some|the)\b)", "", subject, flags=re.I).strip()
    subject = re.sub(
        r"\s+(?:please|pls|plz|thanks|thx|ty|for me|real quick|rq)$",
        "",
        subject,
        flags=re.I,
    ).strip(" \t,.:;!-\"'")

    content_words = [
        word for word in re.findall(r"[a-z0-9]+", subject.lower())
        if word not in _IMAGE_FILLER_WORDS
    ]
    if not content_words:
        return None
    return subject

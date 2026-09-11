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


def sanitize_message(text):
    """Cleans up bot messages to prevent Discord API errors."""
    # Remove @everyone and @here to prevent mass pings
    text = text.replace("@everyone", "").replace("@here", "")
    # Remove duplicate whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    # Discord messages have a 2000 character limit
    if len(text) > 1950:
        text = text[:1950] + "..."
    return text

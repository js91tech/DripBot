import aiohttp
import random
import re


async def search_gif(query):
    """Search Tenor for a random GIF (no API key needed)."""
    url = f"https://tenor.com/search/{query}-gifs"
    try:
        async with aiohttp.ClientSession() as session:
            headers = {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/91.0.4472.124 Safari/537.36"
                )
            }
            async with session.get(
                url, headers=headers
            ) as resp:
                if resp.status == 200:
                    text = await resp.text()
                    gif_urls = re.findall(
                        r'https://media\.tenor\.com/[^"\s]+\.gif',
                        text,
                    )
                    if gif_urls:
                        return random.choice(gif_urls)
    except Exception as e:
        print(f"GIF Search Error: {e}")
    return None


def sanitize_message(text):
    """Clean bot messages for Discord API compliance."""
    text = text.replace("@everyone", "").replace("@here", "")
    text = re.sub(r'\s+', ' ', text).strip()
    if len(text) > 1950:
        text = text[:1950] + "..."
    return text

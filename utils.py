import aiohttp
import re
import random


async def search_gif(query):
    """Searches Tenor directly for a random GIF without needing an API key."""
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
            async with session.get(url, headers=headers) as resp:
                if resp.status == 200:
                    text = await resp.text()
                    gif_urls = re.findall(r'https://media\.tenor\.com/[^"\s]+\.gif', text)
                    if gif_urls:
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

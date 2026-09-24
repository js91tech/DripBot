import json
import os
import re
from collections import Counter
from datetime import datetime, timezone

PEOPLE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "people")
PROFILES_PATH = os.path.join(PEOPLE_DIR, "profiles.json")

IMAGE_REQUEST_RE = re.compile(
    r"\b(draw|drawing|generate|make|create|paint|render|imagine|picture|pic|image|photo|portrait|selfie|art)\b",
    re.IGNORECASE,
)
NSFW_RE = re.compile(
    r"\b(nude|naked|nsfw|sex|porn|xxx|explicit|undress|lingerie|onlyfans|lewd|nsfl)\b",
    re.IGNORECASE,
)
_FALSE_PERSON_PHRASES = (
    "hannah montana",
)

_profiles_cache = None


def _normalize_alias(value):
    return str(value or "").strip().lower()


def load_profiles(force=False):
    global _profiles_cache
    if _profiles_cache is not None and not force:
        return _profiles_cache
    if not os.path.exists(PROFILES_PATH):
        _profiles_cache = []
        return _profiles_cache
    with open(PROFILES_PATH, "r", encoding="utf-8") as f:
        raw = json.load(f)
    profiles = []
    for key, data in raw.items():
        profile = dict(data)
        profile["id"] = key
        aliases = [_normalize_alias(a) for a in profile.get("aliases", [])]
        aliases.append(_normalize_alias(key))
        if profile.get("name"):
            aliases.append(_normalize_alias(profile["name"]))
        profile["aliases"] = sorted({a for a in aliases if a})
        image_name = profile.get("image")
        image_path = os.path.join(PEOPLE_DIR, image_name) if image_name else None
        profile["image_path"] = image_path if image_path and os.path.exists(image_path) else None
        profiles.append(profile)
    _profiles_cache = profiles
    return profiles


def reload_profiles():
    return load_profiles(force=True)


def save_profiles_data(raw):
    os.makedirs(PEOPLE_DIR, exist_ok=True)
    with open(PROFILES_PATH, "w", encoding="utf-8") as f:
        json.dump(raw, f, indent=2, ensure_ascii=False)
        f.write("\n")
    return reload_profiles()


def load_raw_profiles():
    if not os.path.exists(PROFILES_PATH):
        return {}
    with open(PROFILES_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def upsert_profile(profile_id, data):
    raw = load_raw_profiles()
    raw[profile_id] = data
    save_profiles_data(raw)
    return next((p for p in load_profiles() if p["id"] == profile_id), None)


def people_prompt_block():
    lines = []
    for profile in load_profiles():
        notes = " ".join(profile.get("notes") or [])
        lines.append(f"- {profile['name']}: {notes}")
    if not lines:
        return ""
    return (
        "\n\nKNOWN PEOPLE (reference photos on file):\n"
        + "\n".join(lines)
        + "\nIf someone asks you to draw/generate/show a picture of one of these people, "
        "acknowledge it briefly. Image generation is handled separately."
    )


def is_image_request(text):
    return bool(text and IMAGE_REQUEST_RE.search(text))


def is_nsfw_request(text):
    return bool(text and NSFW_RE.search(text))


def _false_person_match(lowered, alias):
    for phrase in _FALSE_PERSON_PHRASES:
        if alias in phrase.split() and phrase in lowered:
            # "hannah" inside "hannah montana" is a different subject.
            remainder = lowered.replace(phrase, " ")
            if not re.search(rf"\b{re.escape(alias)}\b", remainder):
                return True
    return False


def find_person(text):
    if not text:
        return None
    lowered = text.lower()
    matches = []
    for profile in load_profiles():
        for alias in sorted(profile["aliases"], key=len, reverse=True):
            if not alias:
                continue
            if _false_person_match(lowered, alias):
                continue
            if re.search(rf"\b{re.escape(alias)}\b", lowered):
                matches.append((len(alias), profile))
                break
    if not matches:
        return None
    matches.sort(key=lambda item: item[0], reverse=True)
    return matches[0][1]


def find_person_for_image_request(text):
    if not is_image_request(text):
        return None
    return find_person(text)


def profile_from_image_subject(subject):
    """Match a person using the extracted visual subject, not the full chat line."""
    if not subject:
        return None
    return find_person(subject)


def build_image_prompt(profile, user_text):
    appearance = profile.get("appearance", "")
    return (
        f"Create a new photorealistic image of this exact person named {profile['name']}. "
        f"Match their face, hair, glasses, and likeness from the reference photo. "
        f"Appearance: {appearance} "
        f"User request: {(user_text or '').strip()} "
        f"Keep them fully clothed and recognizable as the same person. Do not change their identity."
    )


CLONE_LOOKBACK = 400
FAVORITE_EMOJI_LIMIT = 8
FAVORITE_STICKER_LIMIT = 6

_SLANG_RE = re.compile(
    r"\b(ngl|fr|idk|idc|imo|imho|lowkey|highkey|rn|tbh|lol|lmao|lmfao|bruh|nah|yep|yeth|tf|ikr|smh|ong|bet|w|l)\b",
    re.I,
)
_EMOJI_RE = re.compile(
    "["
    "\U0001F300-\U0001F9FF"
    "\U00002700-\U000027BF"
    "\U0001FA70-\U0001FAFF"
    "]+",
)
CUSTOM_EMOJI_RE = re.compile(r"<a?:\w{1,32}:\d+>")
_UNICODE_EMOJI_RE = re.compile(
    r"(?:[\U0001F1E6-\U0001F1FF]{2}"
    r"|[\U0001F300-\U0001FAFF]"
    r"|[\U00002700-\U000027BF]"
    r"|[\U00002600-\U000026FF])"
    r"\uFE0F?"
)


def extract_emojis_from_text(text):
    """Return custom and unicode emojis found in a Discord message."""
    if not text:
        return []
    found = CUSTOM_EMOJI_RE.findall(text)
    found.extend(_UNICODE_EMOJI_RE.findall(text))
    return found


def rank_favorites(counter, limit):
    return [item for item, _ in Counter(counter).most_common(limit) if item]


def maybe_spice_with_emoji(text, emojis, chance=0.35, rng=None):
    """Sometimes append a favorite emoji when the reply has none yet."""
    import random as random_mod

    if not text or not emojis:
        return text
    if CUSTOM_EMOJI_RE.search(text) or _UNICODE_EMOJI_RE.search(text) or _EMOJI_RE.search(text):
        return text
    picker = rng or random_mod
    if picker.random() > chance:
        return text
    return f"{text} {picker.choice(list(emojis))}"


def favorites_from_settings(settings, personality_name=None):
    """Guild clone_favorites first, then the active people profile."""
    settings = settings or {}
    stored = settings.get("clone_favorites") or {}
    emojis = list(stored.get("emojis") or [])
    stickers = list(stored.get("stickers") or [])
    if emojis or stickers:
        return emojis, stickers
    name = personality_name or settings.get("personality_name") or ""
    preset = ""
    personality = settings.get("personality") or {}
    if isinstance(personality, dict):
        preset = personality.get("preset") or ""
    profile = find_person(name) or find_person(preset)
    if not profile:
        return [], []
    return list(profile.get("favorite_emojis") or []), list(profile.get("favorite_stickers") or [])


def analyze_message_style(messages, emoji_counts=None, sticker_counts=None):
    """Turn a list of message strings into a clone report + Hannah-style prompt notes."""
    texts = [str(m).strip() for m in messages if str(m).strip()]
    extracted = Counter()
    for t in texts:
        extracted.update(extract_emojis_from_text(t))
    if emoji_counts:
        extracted.update(emoji_counts)
    favorite_emojis = rank_favorites(extracted, FAVORITE_EMOJI_LIMIT)
    favorite_stickers = []
    if sticker_counts:
        if isinstance(sticker_counts, dict) and sticker_counts and isinstance(next(iter(sticker_counts.values()), None), dict):
            # {id: {id, name, count?}} ranked by optional count
            ranked = sorted(
                sticker_counts.values(),
                key=lambda item: int(item.get("count") or 0),
                reverse=True,
            )
            favorite_stickers = ranked[:FAVORITE_STICKER_LIMIT]
        else:
            favorite_stickers = list(sticker_counts)[:FAVORITE_STICKER_LIMIT]

    if not texts:
        return {
            "sample_count": 0,
            "avg_chars": 0,
            "median_chars": 0,
            "lowercase_ratio": 0,
            "emoji_ratio": 0,
            "slang": [],
            "common_starters": [],
            "fragments": 0,
            "samples": [],
            "favorite_emojis": favorite_emojis,
            "favorite_stickers": favorite_stickers,
            "summary": "No messages available to analyze.",
        }

    lengths = [len(t) for t in texts]
    lengths_sorted = sorted(lengths)
    mid = len(lengths_sorted) // 2
    if len(lengths_sorted) % 2:
        median = lengths_sorted[mid]
    else:
        median = (lengths_sorted[mid - 1] + lengths_sorted[mid]) / 2

    lower_msgs = sum(1 for t in texts if t[:1].islower())
    emoji_msgs = sum(1 for t in texts if extract_emojis_from_text(t))
    slang = Counter()
    starters = Counter()
    fragments = 0
    for t in texts:
        slang.update(w.lower() for w in _SLANG_RE.findall(t))
        first = re.split(r"[\s,]+", t, maxsplit=1)[0].strip().lower()
        if first:
            starters[first] += 1
        if len(t) <= 18 or not t.endswith((".", "?", "!")):
            fragments += 1

    sticker_bit = (
        f" {len(favorite_stickers)} favorite sticker(s)." if favorite_stickers else ""
    )
    report = {
        "sample_count": len(texts),
        "avg_chars": round(sum(lengths) / len(lengths), 1),
        "median_chars": median,
        "lowercase_ratio": round(lower_msgs / len(texts), 3),
        "emoji_ratio": round(emoji_msgs / len(texts), 3),
        "slang": [w for w, _ in slang.most_common(12)],
        "common_starters": [w for w, _ in starters.most_common(8)],
        "fragments": fragments,
        "samples": texts[:40],
        "favorite_emojis": favorite_emojis,
        "favorite_stickers": favorite_stickers,
        "summary": (
            f"{len(texts)} messages, median {median:g} chars, "
            f"{round(100 * lower_msgs / len(texts))}% start lowercase, "
            f"{round(100 * emoji_msgs / len(texts))}% use emoji."
            f"{sticker_bit}"
        ),
    }
    return report


def build_clone_personality_prompt(name, report, extra_notes=None):
    """Hannah-shaped voice prompt from an observed-style report."""
    slang = ", ".join(report.get("slang") or []) or "whatever they actually type"
    starters = ", ".join(report.get("common_starters") or []) or "short reactions"
    extra = "\n".join(f"- {n}" for n in (extra_notes or []) if n)
    extra_block = f"\nObserved notes:\n{extra}\n" if extra else ""
    median = report.get("median_chars") or 40
    short = "Keep replies very short — fragments are normal." if median <= 40 else (
        "Keep replies short, one or two Discord lines, not a paragraph."
    )
    fav_emojis = [str(e) for e in (report.get("favorite_emojis") or []) if e]
    sticker_names = []
    for sticker in report.get("favorite_stickers") or []:
        if isinstance(sticker, dict) and sticker.get("name"):
            sticker_names.append(sticker["name"])
        elif sticker:
            sticker_names.append(str(sticker))
    emoji_line = (
        f"- Use their favorite emojis the way they do, not every line: {', '.join(fav_emojis)}.\n"
        if fav_emojis else
        "- Use emoji only as often as they would. Do not invent a new emoji personality.\n"
    )
    sticker_line = (
        f"- They send stickers like {', '.join(sticker_names)}. "
        "A sticker may be sent separately; you do not have to mention it.\n"
        if sticker_names else ""
    )
    return (
        f"You are {name} — a real person in this Discord, not a bot or assistant.\n"
        "Your job is to match the observed texting rhythm, humor, bluntness, casual tone, "
        "and group-chat energy as closely as possible.\n"
        "Core voice:\n"
        "Type like this person responding fast in a messy friend group chat. "
        "Not polished. React first, explain later.\n"
        "Message style:\n"
        f"- {short}\n"
        f"- Common slang when it fits: {slang}.\n"
        f"- Common openers: {starters}.\n"
        f"{emoji_line}"
        f"{sticker_line}"
        "- Fragments ok. Casual spelling ok.\n"
        "- Do not sound like an assistant, therapist, poet, or formal writer.\n"
        "- Do not start with names, usernames, or @.\n"
        "- Never claim to be an ai/llm.\n"
        f"{extra_block}"
        "Behavior:\n"
        "- Answer the latest person you are talking to only.\n"
        "- Laugh first if something is funny; ask a short question if confused.\n"
        "- Only join raunchy banter if the chat already went there; keep it joking, never graphic or unsafe.\n"
        "CRITICAL RULE: NEVER include user names, display names, or @ symbols in your actual response text.\n"
        "Default output format:\n"
        "Reply like Discord messages. Short, casual, reactive. One or two tiny lines at most unless asked."
    )


def decode_snowflake(snowflake):
    sid = int(snowflake)
    timestamp_ms = (sid >> 22) + 1420070400000
    sent_at = datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc)
    return {
        "id": str(sid),
        "sent_at": sent_at.isoformat(),
        "worker": (sid & 0x3E0000) >> 17,
        "process": (sid & 0x1F000) >> 12,
        "increment": sid & 0xFFF,
    }


def appearance_from_member(member):
    """Best-effort appearance line when we only have Discord profile fields."""
    bits = []
    display = getattr(member, "display_name", None) or getattr(member, "name", None)
    if display:
        bits.append(f"Goes by {display} in Discord.")
    global_name = getattr(member, "global_name", None)
    if global_name and global_name != display:
        bits.append(f"Global name {global_name}.")
    return " ".join(bits) or "Use the reference photo. Keep them recognizable."

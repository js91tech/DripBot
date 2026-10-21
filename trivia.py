"""Trivia questions, grading, and round setup.

Discord commands live in cogs/trivia.py. This module stays free of Discord
so the rules can be tested on their own.
"""

import random
import re


class TriviaError(Exception):
    """A trivia question or command the bot can explain to a person."""


KINDS = ("multiple_choice", "true_false", "open")
KIND_LABELS = {
    "multiple_choice": "Multiple choice",
    "true_false": "True or false",
    "open": "Open ended",
}
_KIND_TAGS = {
    "multiple_choice": "mc",
    "true_false": "tf",
    "open": "open",
}
_KIND_ALIASES = {
    "mc": "multiple_choice",
    "multiple": "multiple_choice",
    "multiplechoice": "multiple_choice",
    "choice": "multiple_choice",
    "tf": "true_false",
    "truefalse": "true_false",
    "bool": "true_false",
    "boolean": "true_false",
    "open": "open",
    "openended": "open",
    "text": "open",
}

POINTS = {
    "multiple_choice": 1,
    "true_false": 1,
    "open": 2,
}

MAX_BANK = 200
MAX_QUESTION = 300
MAX_CHOICE = 80
MIN_CHOICES = 2
MAX_CHOICES = 6
MAX_EXTRAS = 8
DEFAULT_ROUND = 10
MAX_ROUND = 50

NOT_READY = "Trivia isn't ready yet. Try again in a few seconds."
BUSY = "A trivia round is already running in this channel. `/trivia stop` ends it."
NONE_RUNNING = "No trivia round is running here. Start one with `/trivia start`."
DENIED = "Only the person who started this round, or a server admin, can do that."
BETWEEN = "The next question is on the way."

TRUE_WORDS = {"true", "t", "yes", "y", "yeah", "yep"}
FALSE_WORDS = {"false", "f", "no", "n", "nope", "nah"}
_ARTICLES = {"a", "an", "the"}
_CHATTER = {
    "lol",
    "lmao",
    "lmfao",
    "lmaoo",
    "ok",
    "okay",
    "k",
    "idk",
    "huh",
    "what",
    "wait",
    "bruh",
    "bro",
    "haha",
    "hahaha",
    "hehe",
    "omg",
    "wow",
    "wut",
    "hm",
    "hmm",
    "uh",
    "um",
    "lul",
    "xd",
}
_NUMBER_WORDS = {
    "zero": "0",
    "one": "1",
    "two": "2",
    "three": "3",
    "four": "4",
    "five": "5",
    "six": "6",
    "seven": "7",
    "eight": "8",
    "nine": "9",
    "ten": "10",
    "eleven": "11",
    "twelve": "12",
}
_LABEL = re.compile(r"^[A-Fa-f][).:]\s*")
_EMOJI = re.compile(r"^<a?:[A-Za-z0-9_]+:\d+>$")
_LETTER_WORD = re.compile(r"(?:answer|option|choice)\s+([A-Fa-f])[).:]?", re.IGNORECASE)


HELP_TEXT = """**Trivia mode**
Anyone can play. Server admins (Manage Server) edit the question bank.

**Play**
`!trivia start` — up to 10 questions
`!trivia start 15` — play 15, or `!trivia start all`
`!trivia score` — scores for this round
`!trivia skip` — skip (host or admin)
`!trivia stop` — end the round (host or admin)
`!trivia count` — how many questions are saved

Type your answer in chat. The first correct answer scores.
Multiple choice and true/false are worth 1 point. Open ended is worth 2.

**Admins — add questions**
Multiple choice (2–6 choices). The last part is the correct letter or choice:
`!trivia add mc What is the capital of France? | Paris | London | Berlin | Madrid | a`

True or false:
`!trivia add tf Octopuses have three hearts | true`

Open ended. Extra accepted answers are optional:
`!trivia add open Who wrote Romeo and Juliet? | Shakespeare | William Shakespeare`

**Admins — bank**
`!trivia list` — DM the questions and answers
`!trivia remove 12` — delete question 12
`!trivia loadexamples` — add 5 multiple choice, 5 true/false, and 5 open ended
`!trivia clear confirm` — delete every question in this server

The same actions are available as `/trivia`.
"""

PUBLIC_HELP_TEXT = """**Trivia mode**
Anyone can play. Server admins (Manage Server) edit the question bank.

**Play**
`/trivia start` — up to 10 questions
`/trivia score` — scores for this round
`/trivia skip` — skip (host or admin)
`/trivia stop` — end the round (host or admin)
`/trivia count` — how many questions are saved

Type your answer in chat. The first correct answer scores.
Multiple choice and true/false are worth 1 point. Open ended is worth 2.

**Admins — add questions**
`/trivia add` — multiple choice, true/false, or open ended.
For multiple choice, separate choices with `|`.
The answer is a letter or the exact choice.

**Admins — bank**
`/trivia list` — view questions and answers (only you can see it)
`/trivia remove` — delete one question by id
`/trivia loadexamples` — add 5 multiple choice, 5 true/false, and 5 open ended
`/trivia clear` — delete every question in this server
"""


def clean_text(text):
    collapsed = " ".join(str(text or "").split())
    collapsed = collapsed.replace("@everyone", "@\u200beveryone").replace("@here", "@\u200bhere")
    collapsed = collapsed.replace("<@", "<@\u200b").replace("<#", "<#\u200b")
    return collapsed.replace("`", "'").strip()


def public_name(name):
    cleaned = clean_text(name).replace("*", "").replace("_", "").replace("|", "").strip()
    return cleaned[:80] or "Someone"


def _core(text):
    cleaned = clean_text(text).lower()
    cleaned = re.sub(r"[^a-z0-9\s]", " ", cleaned)
    words = [word for word in cleaned.split() if word not in _ARTICLES]
    return " ".join(words)


def question_key(text):
    return _core(text)


def strip_choice_label(text):
    return _LABEL.sub("", text or "", count=1).strip()


def fold_numbers(text):
    return " ".join(_NUMBER_WORDS.get(word, word) for word in (text or "").split())


def _compact(text):
    return re.sub(r"\s+", "", text or "")


def normalize_kind(token):
    key = re.sub(r"[^a-z]", "", str(token or "").lower())
    return _KIND_ALIASES.get(key)


def kind_label(kind):
    return KIND_LABELS.get(kind, "Trivia")


def seconds_for(kind):
    if kind == "open":
        return 35
    return 20


def _canonical_bool(answer):
    token = _core(answer)
    if token in TRUE_WORDS:
        return "true"
    if token in FALSE_WORDS:
        return "false"
    return None


def _resolve_mc_answer(choices, answer):
    raw = (answer or "").strip()
    letter = re.fullmatch(r"([A-Fa-f])[).:]?", raw)
    if letter:
        index = ord(letter.group(1).lower()) - ord("a")
        if index >= len(choices):
            raise TriviaError(f"There is no choice {letter.group(1).upper()}.")
        return choices[index]
    wanted = _core(strip_choice_label(raw))
    for choice in choices:
        if _core(choice) == wanted:
            return choice
    raise TriviaError(
        "The answer has to be a letter like `b`, or the exact text of the correct choice."
    )


def validate_question(kind, question, choices=None, answer="", accepted=None):
    """Return a normalized question dict, or raise TriviaError."""
    canonical = kind if kind in KINDS else normalize_kind(kind)
    if canonical not in KINDS:
        raise TriviaError("Kind must be multiple choice, true/false, or open ended.")

    question = clean_text(question)
    if len(question) < 8 or not _core(question):
        raise TriviaError("Write a fuller question (at least 8 characters).")
    if len(question) > MAX_QUESTION:
        raise TriviaError(f"Question must be {MAX_QUESTION} characters or fewer.")

    answer = clean_text(answer)
    raw_choices = []
    for choice in choices or []:
        cleaned = strip_choice_label(clean_text(choice))
        if cleaned:
            raw_choices.append(cleaned)

    if canonical == "multiple_choice":
        if not (MIN_CHOICES <= len(raw_choices) <= MAX_CHOICES):
            raise TriviaError(f"Multiple choice needs {MIN_CHOICES} to {MAX_CHOICES} choices.")
        if any(len(choice) > MAX_CHOICE for choice in raw_choices):
            raise TriviaError(f"Each choice must be {MAX_CHOICE} characters or fewer.")
        cores = [_core(choice) for choice in raw_choices]
        if any(not core for core in cores) or len(set(cores)) != len(cores):
            raise TriviaError("Choices have to be different.")
        resolved = _resolve_mc_answer(raw_choices, answer)
        return {
            "kind": canonical,
            "question": question,
            "choices": raw_choices,
            "answer": resolved,
            "accepted": [],
        }

    if canonical == "true_false":
        stored = _canonical_bool(answer)
        if stored is None:
            raise TriviaError("True/false answer must be true or false.")
        return {
            "kind": canonical,
            "question": question,
            "choices": [],
            "answer": stored,
            "accepted": [],
        }

    if not answer or not _core(answer):
        raise TriviaError("Open-ended questions need an answer.")
    if len(answer) > MAX_CHOICE:
        raise TriviaError(f"The answer must be {MAX_CHOICE} characters or fewer.")
    extras = []
    seen = {_core(answer)}
    for item in accepted or []:
        cleaned = clean_text(item)
        if not cleaned:
            continue
        if len(cleaned) > MAX_CHOICE:
            raise TriviaError(f"Each accepted answer must be {MAX_CHOICE} characters or fewer.")
        key = _core(cleaned)
        if not key or key in seen:
            continue
        seen.add(key)
        extras.append(cleaned)
    if len(extras) > MAX_EXTRAS:
        raise TriviaError(f"You can add up to {MAX_EXTRAS} extra accepted answers.")
    return {
        "kind": canonical,
        "question": question,
        "choices": [],
        "answer": answer,
        "accepted": extras,
    }


def parse_trivia_add(payload):
    """Parse `mc|tf|open` text split by `|` into a question dict."""
    text = (payload or "").strip()
    if not text:
        raise TriviaError("Add a question with `mc`, `tf`, or `open`. Try `!trivia help`.")
    kind_token, _, rest = text.partition(" ")
    kind = normalize_kind(kind_token)
    if kind is None or not rest.strip():
        raise TriviaError(
            "Start with `mc`, `tf`, or `open`. Example: `!trivia add tf The sun is a star | true`"
        )
    if "|" not in rest:
        raise TriviaError("Separate the question and the answer with `|`.")
    parts = [clean_text(part) for part in rest.split("|")]
    parts = [part for part in parts if part]
    if kind == "multiple_choice":
        if len(parts) < 4:
            raise TriviaError(
                "Multiple choice needs a question, at least 2 choices, and the answer. "
                "`Question | choice | choice | answer`"
            )
        *head, given = parts
        return validate_question(kind, head[0], head[1:], given, [])
    if kind == "true_false":
        if len(parts) != 2:
            raise TriviaError("True/false format: `Question | true` or `Question | false`.")
        return validate_question(kind, parts[0], [], parts[1], [])
    if len(parts) < 2:
        raise TriviaError("Open format: `Question | answer`. Extra accepted answers can follow another `|`.")
    question, given, *extras = parts
    return validate_question(kind, question, [], given, extras)


def _example_pack():
    specs = [
        (
            "multiple_choice",
            "What is the capital of France?",
            ["Paris", "London", "Berlin", "Madrid"],
            "Paris",
            [],
        ),
        (
            "multiple_choice",
            "How many planets are in our solar system?",
            ["7", "8", "9", "10"],
            "8",
            [],
        ),
        (
            "multiple_choice",
            "Which planet is known as the Red Planet?",
            ["Venus", "Mars", "Jupiter", "Mercury"],
            "Mars",
            [],
        ),
        (
            "multiple_choice",
            "What do bees collect from flowers to make honey?",
            ["Nectar", "Pollen", "Sap", "Dew"],
            "Nectar",
            [],
        ),
        (
            "multiple_choice",
            "How many sides does a hexagon have?",
            ["5", "6", "7", "8"],
            "6",
            [],
        ),
        ("true_false", "Octopuses have three hearts.", [], "true", []),
        ("true_false", "Goldfish only remember things for three seconds.", [], "false", []),
        ("true_false", "Bananas are botanically berries.", [], "true", []),
        ("true_false", "Lightning never strikes the same place twice.", [], "false", []),
        (
            "true_false",
            "The Great Wall of China can be seen from the Moon with the naked eye.",
            [],
            "false",
            [],
        ),
        (
            "open",
            "What is the largest ocean on Earth?",
            [],
            "Pacific",
            ["Pacific Ocean"],
        ),
        (
            "open",
            "Who wrote Romeo and Juliet?",
            [],
            "Shakespeare",
            ["William Shakespeare"],
        ),
        (
            "open",
            "What gas do plants take in from the air for photosynthesis?",
            [],
            "Carbon dioxide",
            ["CO2"],
        ),
        (
            "open",
            "What is the hardest natural substance on Earth?",
            [],
            "Diamond",
            [],
        ),
        (
            "open",
            "In what year did Apollo 11 land on the Moon?",
            [],
            "1969",
            [],
        ),
    ]
    return tuple(validate_question(*spec) for spec in specs)


EXAMPLE_QUESTIONS = _example_pack()


def _is_chatter(text):
    raw = (text or "").strip()
    if not raw or raw.startswith("<@") or raw.startswith("<#") or _EMOJI.fullmatch(raw):
        return True
    # "a" is also a multiple-choice letter, so don't treat it as the article.
    if re.fullmatch(r"[A-Fa-f][).:]?", raw):
        return False
    core = _core(raw)
    return not core or core in _CHATTER


def _mc_letter_index(text, choice_count):
    raw = (text or "").strip()
    match = re.fullmatch(r"([A-Fa-f])[).:]?", raw)
    if match is None:
        match = _LETTER_WORD.fullmatch(raw)
    if match is None:
        return None
    index = ord(match.group(1).lower()) - ord("a")
    if index < 0 or index >= choice_count:
        return None
    return index


def _contains_words(haystack, needle):
    if not needle or len(needle) > len(haystack):
        return False
    width = len(needle)
    for index in range(len(haystack) - width + 1):
        if haystack[index:index + width] == needle:
            return True
    return False


def _open_equal(guess, answer):
    guess_core = fold_numbers(_core(guess))
    answer_core = fold_numbers(_core(answer))
    if not guess_core or not answer_core:
        return False
    if guess_core == answer_core:
        return True
    if _compact(guess_core) == _compact(answer_core) and len(_compact(answer_core)) >= 2:
        return True
    guess_words = guess_core.split()
    answer_words = answer_core.split()
    if len(answer_words) == 1 and len(answer_core) < 4:
        return False
    if len(guess_words) > len(answer_words) + 3:
        return False
    return _contains_words(guess_words, answer_words)


def accepted_answers(question):
    values = [question.get("answer") or ""]
    values.extend(question.get("accepted") or [])
    return [value for value in values if str(value).strip()]


def judge(question, guess):
    """Return True, False, or None.

    True is a correct answer. False is a clear wrong try. None means the
    message is chatter and should not be scored.
    """
    text = (guess or "").strip()
    if not text or len(text) > 140:
        return None
    kind = question.get("kind")
    if kind == "multiple_choice":
        return _judge_multiple_choice(question, text)
    if kind == "true_false":
        return _judge_true_false(question, text)
    if kind == "open":
        return _judge_open(question, text)
    return None


def _judge_multiple_choice(question, text):
    if _is_chatter(text):
        return None
    choices = list(question.get("choices") or [])
    index = _mc_letter_index(text, len(choices))
    if index is not None:
        return _core(choices[index]) == _core(question.get("answer"))
    wanted = _core(strip_choice_label(text))
    if not wanted:
        return None
    for choice in choices:
        if _core(choice) == wanted:
            return _core(choice) == _core(question.get("answer"))
    return None


def _judge_true_false(question, text):
    token = _core(text)
    if token in TRUE_WORDS:
        return question.get("answer") == "true"
    if token in FALSE_WORDS:
        return question.get("answer") == "false"
    return None


def _judge_open(question, text):
    if _is_chatter(text) or len(text) > 100:
        return None
    for answer in accepted_answers(question):
        if _open_equal(text, answer):
            return True
    if _core(text):
        return False
    return None


def format_answer(question):
    if question.get("kind") == "multiple_choice":
        for index, choice in enumerate(question.get("choices") or []):
            if _core(choice) == _core(question.get("answer")):
                return f"{chr(65 + index)}) {choice}"
        return question.get("answer") or ""
    if question.get("kind") == "true_false":
        return "True" if question.get("answer") == "true" else "False"
    return question.get("answer") or ""


def question_card(question, number, total):
    lines = [question["question"], ""]
    if question["kind"] == "multiple_choice":
        for index, choice in enumerate(question["choices"]):
            lines.append(f"**{chr(65 + index)})** {choice}")
        lines.append("")
        lines.append("Reply with the letter or the choice.")
    elif question["kind"] == "true_false":
        lines.append("Reply with true or false.")
    else:
        lines.append("Type the answer.")
    points = POINTS[question["kind"]]
    unit = "point" if points == 1 else "points"
    return {
        "title": f"Trivia {number}/{total} · {kind_label(question['kind'])}",
        "description": "\n".join(lines),
        "footer": f"Worth {points} {unit} · {seconds_for(question['kind'])} seconds",
    }


def format_leaderboard(rows, heading="Trivia scores"):
    title = f"**{heading}**"
    if not rows:
        return f"{title}\nNobody scored."
    lines = [title]
    for index, row in enumerate(rows, 1):
        points = row["points"]
        unit = "point" if points == 1 else "points"
        lines.append(f"{index}. {row['name']} — {points} {unit}")
    return "\n".join(lines)


def kind_counts(questions):
    counts = {kind: 0 for kind in KINDS}
    for question in questions or []:
        kind = question.get("kind")
        if kind in counts:
            counts[kind] += 1
    return counts


def bank_summary(questions):
    counts = kind_counts(questions)
    total = len(questions or [])
    return (
        f"Trivia bank: **{total}** total — "
        f"{counts['multiple_choice']} multiple choice, "
        f"{counts['true_false']} true/false, "
        f"{counts['open']} open ended."
    )


def _paginate(lines, limit=1800):
    pages = []
    current = []
    size = 0
    for line in lines:
        extra = len(line) + (1 if current else 0)
        if current and size + extra > limit:
            pages.append("\n".join(current))
            current = [line]
            size = len(line)
        else:
            current.append(line)
            size += extra
    if current:
        pages.append("\n".join(current))
    return pages


def format_bank(questions):
    if not questions:
        return ["No trivia questions saved yet."]
    lines = ["**Trivia bank**"]
    for question in questions:
        text = question.get("question") or ""
        if len(text) > 90:
            text = text[:87] + "..."
        tag = _KIND_TAGS.get(question.get("kind"), "trivia")
        lines.append(f"`#{question.get('id', '?')}` [{tag}] {text} → {format_answer(question)}")
    return _paginate(lines)


def empty_bank_message():
    return (
        "This server doesn't have trivia questions yet.\n"
        "An admin can add some with `/trivia add`, "
        "or load a sample pack of 5 multiple choice, 5 true/false, and 5 open ended "
        "with `/trivia loadexamples`."
    )


def start_announcement(playing, bank_size, requested):
    word = "question" if playing == 1 else "questions"
    lines = [f"Trivia round starting — **{playing}** {word}."]
    if requested is not None and requested > bank_size:
        lines.append(f"The bank only has {bank_size}, so this round uses all of them.")
    elif playing < bank_size:
        lines.append(f"{bank_size} saved. This round draws {playing}.")
    lines.append("First correct answer scores. Multiple choice and true/false are 1 point. Open ended is 2.")
    lines.append("Type your answer in chat. I'll stay out of the chat until the round ends.")
    lines.append("`/trivia stop` ends the round.")
    return "\n".join(lines)


def examples_loaded_message(added, skipped):
    if added <= 0:
        return "The sample pack is already in this server. Start a round with `/trivia start`."
    word = "question" if added == 1 else "questions"
    return (
        f"Loaded the sample pack: **{added}** new {word}. "
        f"Skipped **{skipped}** already saved.\n"
        "The pack is 5 multiple choice, 5 true/false, and 5 open ended. "
        "Start a round with `/trivia start`."
    )


def parse_round_count(raw):
    if raw is None:
        return None
    text = str(raw).strip().lower()
    if not text:
        return None
    if text == "all":
        return MAX_ROUND
    if text.isdigit():
        count = int(text)
        if 1 <= count <= MAX_ROUND:
            return count
        raise TriviaError(f"A round can be from 1 to {MAX_ROUND} questions.")
    raise TriviaError("Usage: `!trivia start`, `!trivia start 10`, or `!trivia start all`.")


def build_round(questions, count=None, rng=None):
    rng = rng or random
    pool = list(questions or [])
    if not pool:
        return []
    if count is None:
        count = min(DEFAULT_ROUND, len(pool))
    else:
        count = int(count)
    if count < 1:
        return []
    count = min(count, len(pool), MAX_ROUND)
    order = KINDS
    buckets = {}
    for kind in order:
        bucket = [question for question in pool if question.get("kind") == kind]
        rng.shuffle(bucket)
        buckets[kind] = bucket
    leftovers = [question for question in pool if question.get("kind") not in buckets]
    rng.shuffle(leftovers)
    mixed = []
    while len(mixed) < count and any(buckets[kind] for kind in order):
        for kind in order:
            if buckets[kind] and len(mixed) < count:
                mixed.append(buckets[kind].pop())
    if len(mixed) < count:
        mixed.extend(leftovers[: count - len(mixed)])
    return mixed


def find_duplicate(questions, question_text):
    key = question_key(question_text)
    if not key:
        return None
    for question in questions or []:
        if question_key(question.get("question", "")) == key:
            return question
    return None


def chat_should_stay_quiet(content, trivia_active, prefix="!"):
    """Keep the chat personality from answering a live round or a prefix command."""
    if trivia_active:
        return True
    text = (content or "").lstrip()
    pref = prefix or "!"
    if len(text) < len(pref) or not text.lower().startswith(pref.lower()):
        return False
    rest = text[len(pref):]
    return bool(rest) and rest[:1].isalnum()


def should_cancel_task(task, current_task):
    """Cancel a timer unless it is the task currently posting the next question."""
    if task is None or task is current_task:
        return False
    done = getattr(task, "done", None)
    if callable(done) and done():
        return False
    return True


class TriviaSession:
    """One channel's round. Questions are copied in when the round starts."""

    def __init__(self, channel_id, host_id, questions):
        self.channel_id = channel_id
        self.host_id = host_id
        self.questions = list(questions)
        self.index = 0
        self.scores = {}
        self.names = {}
        self.wrong_users = set()
        self.locked = True
        self.token = 0
        self.game_id = id(self)

    def current(self):
        if self.index >= len(self.questions):
            return None
        return self.questions[self.index]

    def open_question(self):
        self.locked = False
        self.wrong_users.clear()
        self.token += 1
        return self.token

    def advance(self):
        self.index += 1
        self.locked = True
        self.wrong_users.clear()
        self.token += 1

    def submit(self, user_id, display_name, guess):
        if self.locked or self.current() is None:
            return {"status": "closed"}
        question = self.current()
        verdict = judge(question, guess)
        if verdict is None:
            return {"status": "ignore"}
        if verdict:
            self.locked = True
            points = POINTS[question["kind"]]
            self.scores[user_id] = self.scores.get(user_id, 0) + points
            self.names[user_id] = public_name(display_name)
            return {
                "status": "correct",
                "points": points,
                "total": self.scores[user_id],
                "display": format_answer(question),
            }
        if user_id in self.wrong_users:
            return {"status": "ignore"}
        self.wrong_users.add(user_id)
        return {"status": "wrong"}

    def leaderboard(self):
        rows = []
        for user_id, points in self.scores.items():
            if points <= 0:
                continue
            rows.append(
                {
                    "user_id": user_id,
                    "name": self.names.get(user_id) or str(user_id),
                    "points": points,
                }
            )
        rows.sort(key=lambda row: (-row["points"], row["name"].lower(), row["user_id"]))
        return rows

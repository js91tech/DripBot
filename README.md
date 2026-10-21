# discord-markov-bot

## Trivia mode

Admins (Manage Server or Administrator) build a per-server question bank:

- `/triviaadmin add_mc` – multiple choice (correct answer + 1-3 wrong answers)
- `/triviaadmin add_tf` – true/false
- `/triviaadmin add_open` – open ended (optional comma-separated alternate answers)
- `/triviaadmin list`, `/triviaadmin remove <id>`, `/triviaadmin clear`

Anyone can play:

- `/trivia start` – round of 5 multiple choice, 5 true/false and 5 open ended questions (counts adjustable)
- `/trivia stop`, `/trivia leaderboard`, `/trivia bank`

Multiple choice and true/false use buttons (1 point each); open ended questions are answered by typing in the channel (first correct answer wins 2 points). The bot's normal chatting pauses in that channel while a round is running.

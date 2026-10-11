# Crip Mac Clone Report

Profile id: `cripmac`
Aliases: `cripmac`, `crip mac`, `c-mac`, `cmac`, `c mac`, `trevor hurd`

## Personality Preset & Clone

Crip Mac (Trevor Hurd) is wired as a selectable personality preset and as a **people dataset** entry:

1. `people/profiles.json` — profile metadata, appearance, notes, aliases
2. `config/default_settings.py` — canonical `cripmac` preset in `PERSONALITY_PRESETS` and aliases in `PERSONALITY_ALIASES`
3. `cogs/settings_cog.py` — labeled choice in `/botsettings personality` slash command dropdown
4. `dashboard.html` & `api.py` — selectable preset card in the web dashboard
5. `llm.py` — natural language setting change support (`switch personality to cripmac`)
6. Chat + `/imagine` detect `draw cripmac` / `draw crip mac`
7. Photorealistic likeness preservation in image prompt generation
8. NSFW requests refused

## How to Select Crip Mac

- Slash command: `/botsettings personality preset:Crip Mac (55th Street Legend)`
- Text command: `!personality cripmac` (or `!personality crip mac`, `!personality c-mac`)
- Natural language: `/botsettings ask prompt:switch personality to cripmac`
- Settings command: `/botsettings set key:personality value:cripmac`
- Web dashboard: click the **Crip Mac** preset card under Personality

## How to Ask for Images

- `draw cripmac`
- `draw crip mac as an astronaut`
- `/imagine person:Crip Mac prompt:eating pizza on 55th street`

# discord-markov-bot

## Keeping the bot online

The bot process must keep running for Discord to show it online. On Render, deploy
it as a **web service** so the FastAPI dashboard exposes `/api/health`; background
workers do not expose an HTTP endpoint for uptime checks.

For best uptime on free/idle-sleeping hosts:

- Set `KEEP_ALIVE_URL` to the public health URL, for example
  `https://your-service.onrender.com/api/health`.
- Add an external uptime monitor that pings the same URL every 5-10 minutes.
- Use a paid always-on worker/web service if you need true 24/7 availability.

The built-in keep-alive can only ping while the process is already running. If the
hosting platform sleeps or stops the container, an external monitor or always-on
plan is required to wake/avoid that.
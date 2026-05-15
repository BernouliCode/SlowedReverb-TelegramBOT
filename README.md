# Slowed + Reverb Telegram Bot

Sends back slowed + reverb versions of audio files or YouTube links.

## Setup

### 1. Install system dependency
`ffmpeg` is required for audio decoding and YouTube extraction.

```bash
# Debian/Ubuntu
sudo apt install ffmpeg

# macOS
brew install ffmpeg
```

### 2. Install Python deps
```bash
pip install -r requirements.txt
```

### 3. Get a bot token
Talk to [@BotFather](https://t.me/BotFather) on Telegram, run `/newbot`, copy the token.

### 4. Set up the shared channel
1. Create a Telegram channel (private is fine — invite your friends).
2. Add your bot to the channel as an **admin** with "Post Messages" permission.
3. Get the channel ID:
   - **Public channel:** use `@yourchannelname`
   - **Private channel:** forward any message from the channel to [@userinfobot](https://t.me/userinfobot) — it'll show an ID like `-1001234567890`. That's your `CHANNEL_ID`.

### 5. Run
```bash
export BOT_TOKEN="123456:ABC-your-token-here"
export CHANNEL_ID="-1001234567890"   # or "@yourchannel" for public
python slowed_reverb_bot.py
```

> Skip `CHANNEL_ID` if you just want personal use — bot will work without channel mirroring.

## Usage
- Send any audio file or YouTube link → bot returns slowed+reverb to **you** AND posts to the **shared channel**
- `/preset` — switch between **light**, **classic**, **deep**, **sleepy**
- `/private` — your *next* track stays between you and the bot, won't be posted to the shared playlist
- The channel becomes the playlist: scroll, search, pin favorites, share invite link with friends

## How it works
- **Slowed**: resamples at a lower rate then plays at the new rate, dropping pitch with tempo (the authentic vaporwave/slowed effect, not pitch-preserving).
- **Reverb**: Spotify's `pedalboard` library, room-size and wet-level tuned per preset.

## Limits (default)
- 50 MB per file (Telegram bot API limit without a local Bot API server)
- 10 min per track (configurable via `MAX_DURATION_SEC`)

To go bigger, run a [local Bot API server](https://github.com/tdlib/telegram-bot-api) — the file limit jumps to 2 GB.

## Deployment notes
- Single-process polling is fine for low traffic. For real load, switch to webhook + a queue (Redis + RQ, or Celery) so heavy ffmpeg/librosa work doesn't block.
- Per-user `ctx.user_data` is in-memory; restarts wipe preset choices. Swap in `PicklePersistence` if you care.

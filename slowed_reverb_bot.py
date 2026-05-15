"""
Telegram Bot: Slowed + Reverb Song Generator
Accepts audio files or YouTube links, returns slowed + reverb versions.
"""

import os
import logging
import tempfile
import asyncio
from pathlib import Path

import numpy as np
import soundfile as sf
from pedalboard import Pedalboard, Reverb
from pedalboard.io import AudioFile
import librosa
import yt_dlp

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

# ---------- Configuration ----------
BOT_TOKEN = os.environ.get("BOT_TOKEN", "PUT_YOUR_TOKEN_HERE")
# Shared channel where every processed track is mirrored.
# Format: "@channelusername" for public channels, or "-1001234567890" for private.
# Leave empty to disable channel posting.
CHANNEL_ID = os.environ.get("CHANNEL_ID", "")
MAX_FILE_SIZE_MB = 50          # Telegram bot upload limit (50MB without local API)
MAX_DURATION_SEC = 600         # 10 min cap to keep processing snappy
WORK_DIR = Path(tempfile.gettempdir()) / "slowedbot"
WORK_DIR.mkdir(exist_ok=True)

# Presets: (speed_factor, reverb_room_size, reverb_wet_level)
PRESETS = {
    "light":    (0.92, 0.55, 0.25),   # subtle vibe
    "classic":  (0.85, 0.75, 0.35),   # the standard slowed+reverb
    "deep":     (0.78, 0.90, 0.45),   # heavy, dreamy
    "sleepy":   (0.70, 0.95, 0.50),   # extreme, ambient
}

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


# ---------- Audio Processing ----------
def slow_and_reverb(input_path: str, output_path: str,
                    speed: float, room_size: float, wet: float) -> None:
    """
    Slow down audio (pitch drops naturally) and apply reverb.
    Uses simple resampling for the classic 'slowed' pitch-down effect.
    """
    # Load audio (mono=False keeps stereo)
    audio, sr = librosa.load(input_path, sr=None, mono=False)

    # Ensure shape is (channels, samples)
    if audio.ndim == 1:
        audio = np.stack([audio, audio])

    # Slowed effect: resample to a lower sample rate, then play back at original
    # This is the authentic "slowed + reverb" approach (pitch drops with tempo)
    new_sr = int(sr * speed)

    # Apply reverb with pedalboard
    board = Pedalboard([
        Reverb(
            room_size=room_size,
            damping=0.5,
            wet_level=wet,
            dry_level=0.75,
            width=1.0,
        )
    ])

    # Pedalboard wants shape (channels, samples), float32
    audio = audio.astype(np.float32)
    processed = board(audio, sample_rate=new_sr)

    # Normalize to prevent clipping
    peak = np.max(np.abs(processed))
    if peak > 0.99:
        processed = processed * (0.99 / peak)

    # WAV output works cross-platform without needing libsndfile MP3 support
    sf.write(output_path, processed.T, new_sr, subtype="PCM_16", format="WAV")

def download_youtube(url: str, out_dir: Path) -> tuple[str, str]:
    """Download audio from a YouTube URL. Returns (filepath, title)."""
    out_template = str(out_dir / "%(id)s.%(ext)s")
    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": out_template,
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192",
        }],
        "quiet": True,
        "no_warnings": True,
        "max_filesize": MAX_FILE_SIZE_MB * 1024 * 1024,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        if info.get("duration", 0) > MAX_DURATION_SEC:
            raise ValueError(f"Track too long (max {MAX_DURATION_SEC // 60} min).")
        filepath = out_dir / f"{info['id']}.mp3"
        return str(filepath), info.get("title", "track")


# ---------- Bot Handlers ----------
WELCOME = (
    "🎧 *Slowed + Reverb Bot*\n\n"
    "Send me an audio file or a YouTube link and I'll make a "
    "slowed + reverb version.\n\n"
    "*Commands:*\n"
    "/preset – pick a vibe (light, classic, deep, sleepy)\n"
    "/private – process your next track *without* posting to the shared playlist\n"
    "/help – show this message\n\n"
    f"_Limits: {MAX_FILE_SIZE_MB} MB, {MAX_DURATION_SEC // 60} min._"
)


async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data.setdefault("preset", "classic")
    await update.message.reply_text(WELCOME, parse_mode="Markdown")


async def help_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(WELCOME, parse_mode="Markdown")


async def preset_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    current = ctx.user_data.get("preset", "classic")
    keyboard = [
        [InlineKeyboardButton(
            f"{'✅ ' if name == current else ''}{name.title()}",
            callback_data=f"preset:{name}",
        )]
        for name in PRESETS
    ]
    await update.message.reply_text(
        f"Current preset: *{current}*\nPick a new vibe:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown",
    )


async def preset_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    name = query.data.split(":", 1)[1]
    if name in PRESETS:
        ctx.user_data["preset"] = name
        await query.edit_message_text(f"✅ Preset set to *{name}*", parse_mode="Markdown")


async def private_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Mark the next track as private (won't be posted to shared channel)."""
    ctx.user_data["skip_channel"] = True
    await update.message.reply_text(
        "🔒 Your *next* track will stay private — won't be posted to the shared playlist.",
        parse_mode="Markdown",
    )


async def process_and_send(update: Update, ctx: ContextTypes.DEFAULT_TYPE,
                           input_path: str, title: str):
    """Apply the effect, send to user, and mirror to shared channel."""
    preset_name = ctx.user_data.get("preset", "classic")
    speed, room, wet = PRESETS[preset_name]
    skip_channel = ctx.user_data.pop("skip_channel", False)

    status = await update.message.reply_text(
        f"⚙️ Processing with *{preset_name}* preset…", parse_mode="Markdown"
    )

    output_path = str(WORK_DIR / f"out_{os.getpid()}_{Path(input_path).stem}.wav")
    
    try:
        # Run heavy processing in a thread so we don't block the event loop
        await asyncio.to_thread(
            slow_and_reverb, input_path, output_path, speed, room, wet
        )

        await status.edit_text("📤 Uploading…")

        # Send to the user who requested it
        with open(output_path, "rb") as f:
            sent = await update.message.reply_audio(
                audio=f,
                title=f"{title} (slowed + reverb)",
                caption=f"🎶 *{title}*\nPreset: `{preset_name}`",
                parse_mode="Markdown",
            )

        # Mirror to the shared channel (re-uses Telegram's file_id — no re-upload)
        if CHANNEL_ID and not skip_channel:
            user = update.effective_user
            requester = f"@{user.username}" if user.username else user.first_name
            try:
                await ctx.bot.send_audio(
                    chat_id=CHANNEL_ID,
                    audio=sent.audio.file_id,
                    caption=(
                        f"🎶 *{title}*\n"
                        f"Preset: `{preset_name}` · requested by {requester}"
                    ),
                    parse_mode="Markdown",
                )
            except Exception as e:
                logger.warning("Channel post failed: %s", e)
                await update.message.reply_text(
                    "⚠️ Couldn't post to the shared playlist (your copy is fine above)."
                )

        await status.delete()

    except Exception as e:
        logger.exception("Processing failed")
        await status.edit_text(f"❌ Error: {e}")
    finally:
        for p in (input_path, output_path):
            try:
                os.remove(p)
            except OSError:
                pass


async def handle_audio(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    file_obj = msg.audio or msg.voice or msg.document

    if not file_obj:
        return

    if file_obj.file_size and file_obj.file_size > MAX_FILE_SIZE_MB * 1024 * 1024:
        await msg.reply_text(f"❌ File too big (max {MAX_FILE_SIZE_MB} MB).")
        return

    title = getattr(file_obj, "title", None) or getattr(file_obj, "file_name", None) or "track"
    title = Path(title).stem

    await msg.reply_text("⬇️ Downloading your file…")
    tg_file = await file_obj.get_file()
    suffix = Path(getattr(file_obj, "file_name", "audio.mp3")).suffix or ".mp3"
    input_path = str(WORK_DIR / f"in_{file_obj.file_unique_id}{suffix}")
    await tg_file.download_to_drive(input_path)

    await process_and_send(update, ctx, input_path, title)


async def handle_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if "youtube.com" in text or "youtu.be" in text:
        status = await update.message.reply_text("⬇️ Fetching from YouTube…")
        try:
            input_path, title = await asyncio.to_thread(download_youtube, text, WORK_DIR)
            await status.delete()
            await process_and_send(update, ctx, input_path, title)
        except Exception as e:
            await status.edit_text(f"❌ Couldn't download: {e}")
    else:
        await update.message.reply_text(
            "Send me an audio file or a YouTube link. /help for details."
        )


# ---------- Main ----------
def main():
    if BOT_TOKEN == "PUT_YOUR_TOKEN_HERE":
        raise SystemExit("Set the BOT_TOKEN environment variable.")

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("preset", preset_cmd))
    app.add_handler(CommandHandler("private", private_cmd))
    app.add_handler(CallbackQueryHandler(preset_callback, pattern=r"^preset:"))
    app.add_handler(MessageHandler(filters.AUDIO | filters.VOICE | filters.Document.AUDIO, handle_audio))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    logger.info("Bot starting…")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()

FROM python:3.11-slim

# System libraries:
#   ffmpeg     -> audio decoding + YouTube extraction
#   libatomic1 -> required by pedalboard (the reverb engine)
RUN apt-get update && apt-get install -y \
    ffmpeg \
    libatomic1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies first (better layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the code
COPY . .

# Start the bot
CMD ["python", "slowed_reverb_bot.py"]

# ── Empathy Engine — Dockerfile ──────────────────────────────────────────────
# Python 3.11 (stable, has pyaudioop — but we don't use pydub anyway)
# ffmpeg installed via apt so no PATH issues on any OS
FROM python:3.11-slim

# Install ffmpeg system-wide (available to subprocess calls in app.py)
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy and install Python dependencies first (layer cache friendly)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the project
COPY . .

# Create audio output directory
RUN mkdir -p static/audio

# Expose Flask port
EXPOSE 5000

# Run the app
CMD ["python", "app.py"]

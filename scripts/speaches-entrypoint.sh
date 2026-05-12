#!/bin/sh
# speaches-entrypoint.sh - Start Speaches server and preload the STT model.
# Sends a tiny transcription request so the Whisper model is loaded into memory.

# Start Speaches server in the background using its default command
cd /home/ubuntu/speaches
.venv/bin/python -m uvicorn speaches.main:create_app --factory --host 0.0.0.0 --port 8000 &
SERVER_PID=$!

# Wait for server to be ready
echo "[entrypoint] Waiting for Speaches server to start ..."
elapsed=0
while ! curl -sf http://localhost:8000/health > /dev/null 2>&1; do
  sleep 2
  elapsed=$((elapsed + 2))
  if [ "$elapsed" -ge 120 ]; then
    echo "[entrypoint] ERROR: Speaches server did not start within 120s"
    wait $SERVER_PID
    exit 1
  fi
done
echo "[entrypoint] Speaches server is ready (took ~${elapsed}s)."

# Generate a tiny silent WAV file (1 second, 16kHz, mono, 16-bit PCM)
# WAV header (44 bytes) + 32000 bytes of silence = 32044 bytes total
python3 -c "
import struct, sys
sr=16000; ch=1; bps=16; dur=1
data_size = sr * ch * (bps//8) * dur
# RIFF header
sys.stdout.buffer.write(b'RIFF')
sys.stdout.buffer.write(struct.pack('<I', 36 + data_size))
sys.stdout.buffer.write(b'WAVE')
# fmt chunk
sys.stdout.buffer.write(b'fmt ')
sys.stdout.buffer.write(struct.pack('<IHHIIHH', 16, 1, ch, sr, sr*ch*(bps//8), ch*(bps//8), bps))
# data chunk
sys.stdout.buffer.write(b'data')
sys.stdout.buffer.write(struct.pack('<I', data_size))
sys.stdout.buffer.write(b'\x00' * data_size)
" > /tmp/silence.wav

# Send a transcription request to preload the STT model
echo "[entrypoint] Preloading STT model (Whisper) ..."
curl -s --max-time 300 \
  -X POST http://localhost:8000/v1/audio/transcriptions \
  -F "file=@/tmp/silence.wav" \
  -F "model=Systran/faster-whisper-small" \
  > /dev/null 2>&1
echo "[entrypoint] STT model preloaded. Done."

rm -f /tmp/silence.wav

# Keep the server running in the foreground
wait $SERVER_PID

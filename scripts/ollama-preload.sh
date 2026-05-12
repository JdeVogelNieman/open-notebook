#!/bin/sh
# ollama-entrypoint.sh - Start Ollama server and preload a model into memory.
# Prefers gemma4; falls back to first available model.
# Uses only the ollama CLI (no curl/wget needed).

PREFERRED_MODEL="${PREFERRED_MODEL:-gemma4}"

# Start Ollama server in the background
ollama serve &
SERVER_PID=$!

# Wait for server to be ready (ollama list will fail until server is up)
echo "[entrypoint] Waiting for Ollama server to start ..."
elapsed=0
while ! ollama list > /dev/null 2>&1; do
  sleep 2
  elapsed=$((elapsed + 2))
  if [ "$elapsed" -ge 120 ]; then
    echo "[entrypoint] ERROR: Ollama server did not start within 120s"
    wait $SERVER_PID
    exit 1
  fi
done
echo "[entrypoint] Ollama server is ready (took ~${elapsed}s)."

# List locally-available models (skip header line)
MODELS=$(ollama list 2>/dev/null | tail -n +2 | awk '{print $1}')

if [ -z "$MODELS" ]; then
  echo "[entrypoint] No models found. Skipping preload."
else
  echo "[entrypoint] Available models:"
  echo "$MODELS"

  TARGET=""
  for m in $MODELS; do
    case "$m" in
      ${PREFERRED_MODEL}*) TARGET="$m"; break ;;
    esac
  done

  if [ -z "$TARGET" ]; then
    TARGET=$(echo "$MODELS" | head -n1)
    echo "[entrypoint] ${PREFERRED_MODEL} not found; falling back to: ${TARGET}"
  else
    echo "[entrypoint] Found preferred model: ${TARGET}"
  fi

  echo "[entrypoint] Loading ${TARGET} into memory ..."
  echo "hi" | ollama run "$TARGET" > /dev/null 2>&1
  echo "[entrypoint] Model ${TARGET} is loaded. Done."
fi

# Keep the server running in the foreground
wait $SERVER_PID

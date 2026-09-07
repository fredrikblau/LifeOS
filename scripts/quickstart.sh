#!/bin/bash
# LifeOS Quickstart
# =================
#
# One interactive pass from a fresh clone to a running assistant: it checks the
# prerequisites, builds the venv, asks the handful of questions that actually
# have to be answered, and writes a .env you can read.
#
# It is deliberately narrow. It configures the *core* — a vault, one LLM
# provider, optionally Telegram — and nothing else. Google, Slack, Monarch,
# Apple and the agent worker are all addable later without touching this
# script; see docs/guides/configuration.md.
#
# Safe to re-run: an existing .env is never overwritten silently, and every
# prompt offers the current value as its default.
#
# Usage: ./scripts/quickstart.sh [--no-install]
#
#   --no-install   Skip venv creation and pip install (configuration only).

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR" || exit 1

ENV_FILE="$PROJECT_DIR/.env"
VENV_DIR="${LIFEOS_VENV:-$HOME/.venvs/lifeos}"
DO_INSTALL=true
[ "${1:-}" = "--no-install" ] && DO_INSTALL=false

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'
BLUE='\033[0;34m'; CYAN='\033[0;36m'; NC='\033[0m'
info()    { echo -e "${GREEN}[INFO]${NC} $1"; }
warn()    { echo -e "${YELLOW}[WARN]${NC} $1"; }
err()     { echo -e "${RED}[ERROR]${NC} $1"; }
step()    { echo -e "\n${BLUE}[====]${NC} ${CYAN}$1${NC}"; }

# Read a KEY=value out of an existing .env so re-runs can offer it as default.
current() {
    [ -f "$ENV_FILE" ] || return 0
    grep -E "^${1}=" "$ENV_FILE" 2>/dev/null | tail -1 | cut -d= -f2- \
        | sed "s/^['\"]//;s/['\"]\$//"
}

# ask VAR "Prompt" [default]
ask() {
    local var="$1" prompt="$2" default="${3:-}" reply
    if [ -n "$default" ]; then
        read -r -p "$(echo -e "  ${prompt} [${default}]: ")" reply
        reply="${reply:-$default}"
    else
        read -r -p "$(echo -e "  ${prompt}: ")" reply
    fi
    printf -v "$var" '%s' "$reply"
}

# --------------------------------------------------------------------------
step "Checking prerequisites"

PYTHON_BIN=""
for candidate in python3.13 python3.12 python3.11 python3; do
    command -v "$candidate" >/dev/null 2>&1 || continue
    if "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
        PYTHON_BIN="$candidate"
        break
    fi
done
if [ -z "$PYTHON_BIN" ]; then
    err "Python 3.11+ is required and was not found on PATH."
    exit 1
fi
info "Using $($PYTHON_BIN --version) at $(command -v "$PYTHON_BIN")"

# --------------------------------------------------------------------------
step "Configuration"

if [ -f "$ENV_FILE" ]; then
    info "Found an existing .env — every prompt defaults to its current value."
fi

echo
echo "  Your vault is any folder of markdown notes (an Obsidian vault, or an"
echo "  empty folder to start from nothing). LifeOS reads and writes here."
ask VAULT_PATH "Vault path" "$(current LIFEOS_VAULT_PATH || echo "$PROJECT_DIR/vault")"
VAULT_PATH="${VAULT_PATH/#\~/$HOME}"

echo
echo "  Which LLM provider should answer? You need an API key for whichever"
echo "  you pick (or 'local' for a llama-server you run yourself)."
echo "    anthropic  openai  deepseek  gemini  openrouter  groq  mistral  local"
ask LLM_PROVIDER "Provider" "$(current LIFEOS_LLM_PROVIDER || echo anthropic)"
LLM_PROVIDER="$(echo "$LLM_PROVIDER" | tr '[:upper:]' '[:lower:]' | tr -d '[:space:]')"

case "$LLM_PROVIDER" in
    anthropic)  KEY_VAR=ANTHROPIC_API_KEY ;;
    openai)     KEY_VAR=OPENAI_API_KEY ;;
    deepseek)   KEY_VAR=DEEPSEEK_API_KEY ;;
    gemini)     KEY_VAR=GEMINI_API_KEY ;;
    openrouter) KEY_VAR=OPENROUTER_API_KEY ;;
    groq)       KEY_VAR=GROQ_API_KEY ;;
    mistral)    KEY_VAR=MISTRAL_API_KEY ;;
    local)      KEY_VAR="" ;;
    *)
        err "Unknown provider '$LLM_PROVIDER'."
        exit 1
        ;;
esac

API_KEY=""
if [ -n "$KEY_VAR" ]; then
    ask API_KEY "$KEY_VAR" "$(current "$KEY_VAR")"
    [ -n "$API_KEY" ] || warn "No key given — chat will fail until $KEY_VAR is set in .env."
fi

echo
echo "  Telegram is the primary way to talk to LifeOS when it runs on a server."
echo "  Create a bot with @BotFather; leave blank to skip and add it later."
ask TG_TOKEN "Telegram bot token" "$(current TELEGRAM_BOT_TOKEN)"
if [ -n "$TG_TOKEN" ]; then
    echo "  Your numeric Telegram user id (from @userinfobot). Only this id is"
    echo "  allowed to talk to the bot."
    ask TG_CHAT "Telegram chat id" "$(current TELEGRAM_CHAT_ID)"
fi

echo
ask TZ_NAME "Timezone (IANA, e.g. Europe/Berlin)" \
    "$(current LIFEOS_TIMEZONE || cat /etc/timezone 2>/dev/null || echo UTC)"
ask USER_NAME "Your name (how the assistant addresses you)" \
    "$(current LIFEOS_USER_NAME || echo "$USER")"

echo
echo "  If this machine has a public IP, the API must not be open to it: LifeOS"
echo "  serves your whole personal record and has no login of its own."
API_TOKEN="$(current LIFEOS_API_TOKEN)"
if [ -z "$API_TOKEN" ]; then
    ask GEN_TOKEN "Generate an API access token? (Y/n)" "Y"
    case "$GEN_TOKEN" in
        [Nn]*) API_TOKEN="" ;;
        *) API_TOKEN="$("$PYTHON_BIN" -c 'import secrets; print(secrets.token_urlsafe(32))')" ;;
    esac
fi

# --------------------------------------------------------------------------
step "Writing .env"

if [ -f "$ENV_FILE" ]; then
    BACKUP="$ENV_FILE.backup-$(date +%Y%m%d%H%M%S)"
    cp "$ENV_FILE" "$BACKUP"
    info "Backed up your current .env to $(basename "$BACKUP")"
fi

{
    echo "# Written by scripts/quickstart.sh on $(date -Iseconds)."
    echo "# Every setting is documented in docs/guides/configuration.md."
    echo
    echo "LIFEOS_VAULT_PATH=$VAULT_PATH"
    echo "LIFEOS_USER_NAME=$USER_NAME"
    echo "LIFEOS_TIMEZONE=$TZ_NAME"
    echo
    echo "# --- LLM ---"
    echo "LIFEOS_LLM_PROVIDER=$LLM_PROVIDER"
    [ -n "$KEY_VAR" ] && echo "$KEY_VAR=$API_KEY"
    echo
    echo "# --- Telegram ---"
    if [ -n "$TG_TOKEN" ]; then
        echo "TELEGRAM_BOT_TOKEN=$TG_TOKEN"
        echo "TELEGRAM_CHAT_ID=${TG_CHAT:-}"
    else
        echo "# TELEGRAM_BOT_TOKEN="
        echo "# TELEGRAM_CHAT_ID="
    fi
    echo
    echo "# --- Server ---"
    if [ -n "$API_TOKEN" ]; then
        echo "LIFEOS_API_TOKEN=$API_TOKEN"
    else
        echo "# LIFEOS_API_TOKEN="
    fi
    echo "LIFEOS_CHROMA_PATH=./data/chromadb"
    echo "LIFEOS_PORT=8000"
} > "$ENV_FILE"
chmod 600 "$ENV_FILE"
info "Wrote $ENV_FILE (mode 600)"

mkdir -p "$VAULT_PATH" "$PROJECT_DIR/data" "$PROJECT_DIR/logs"

# --------------------------------------------------------------------------
if [ "$DO_INSTALL" = true ]; then
    step "Installing dependencies (this takes a few minutes)"
    if [ ! -d "$VENV_DIR" ]; then
        "$PYTHON_BIN" -m venv "$VENV_DIR" || { err "Could not create $VENV_DIR"; exit 1; }
        info "Created virtualenv at $VENV_DIR"
    fi
    "$VENV_DIR/bin/pip" install --quiet --upgrade pip
    if ! "$VENV_DIR/bin/pip" install -r "$PROJECT_DIR/requirements.txt"; then
        err "Dependency installation failed. Fix the error above and re-run."
        exit 1
    fi
    info "Dependencies installed"
else
    step "Skipping dependency install (--no-install)"
fi

# --------------------------------------------------------------------------
step "Next steps"

cat <<TXT

  1. Start ChromaDB and the API:

       ./scripts/chromadb.sh start
       ./scripts/server.sh start

     On Linux, to run both as services that survive a reboot:

       sudo ./scripts/setup-systemd.sh

  2. Check it came up:

       curl -s localhost:8000/health

  3. Talk to it. Message your Telegram bot, or open the web chat at
     http://localhost:8000/chat
TXT

if [ -n "$API_TOKEN" ]; then
cat <<TXT

     The API now requires a token from anything that isn't localhost. To open
     the web UI from another machine, visit it once with the token attached:

       http://<this-host>:8000/chat?token=$API_TOKEN

     It is stored as a cookie after that. The token is in your .env.
TXT
fi

cat <<TXT

  Do not leave port 8000 reachable from the internet. Bind it to localhost
  (LIFEOS_HOST=127.0.0.1), firewall it, or keep it behind a VPN.

  Add Google, Slack, Monarch, Apple data or the agent worker whenever you want:
  docs/guides/configuration.md

TXT
info "Quickstart complete."

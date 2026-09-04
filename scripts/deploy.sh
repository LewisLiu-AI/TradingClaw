#!/usr/bin/env bash
#
# deploy.sh — Deploy this repository's working tree to the vibe-trading production server.
#
# Encapsulates the validated update flow (2026-08-09, 0.1.11 → 0.1.13):
#   backup → rsync code → fix ownership → pip install → restart systemd → verify health
#
# Usage:
#   ./scripts/deploy.sh                    full deploy (builds frontend, updates deps, restarts)
#   ./scripts/deploy.sh --dry-run          print every step without executing anything
#   ./scripts/deploy.sh --skip-build       reuse existing frontend/dist (no npm run build)
#   ./scripts/deploy.sh --skip-deps        do not re-run pip install on the server
#   ./scripts/deploy.sh --rollback         restore the latest server backup and restart
#   ./scripts/deploy.sh --rollback=<file>  restore a specific backup (path on the server)
#   ./scripts/deploy.sh --setup-key        copy your local SSH pubkey to the server (asks password once)
#   ./scripts/deploy.sh --force            allow deploy despite uncommitted tracked changes
#
# Server defaults (override via env):
#   DEPLOY_HOST=47.100.42.183   DEPLOY_USER=root   DEPLOY_PORT=22
#   DEPLOY_APP_DIR=/opt/vibe-trading   DEPLOY_SERVICE=vibe-trading
#   DEPLOY_BACKUP_DIR=/opt/backups   DEPLOY_HTTP_PORT=18688
#   PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/
#
# Auth: prefers SSH key (run ./scripts/deploy.sh --setup-key once); falls back to password prompt.
set -uo pipefail

DEPLOY_HOST="${DEPLOY_HOST:-47.100.42.183}"
DEPLOY_USER="${DEPLOY_USER:-root}"
DEPLOY_PORT="${DEPLOY_PORT:-22}"
DEPLOY_APP_DIR="${DEPLOY_APP_DIR:-/opt/vibe-trading}"
DEPLOY_SERVICE="${DEPLOY_SERVICE:-vibe-trading}"
DEPLOY_BACKUP_DIR="${DEPLOY_BACKUP_DIR:-/opt/backups}"
DEPLOY_HTTP_PORT="${DEPLOY_HTTP_PORT:-18688}"
PIP_INDEX_URL="${PIP_INDEX_URL:-https://mirrors.aliyun.com/pypi/simple/}"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

ACTION=deploy
DRY_RUN=0
SKIP_BUILD=0
SKIP_DEPS=0
FORCE=0
ROLLBACK_FILE=""

log()  { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m==>\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31mFAIL\033[0m %s\n' "$*" >&2; exit 1; }

# ---- argument parsing ---------------------------------------------------------
for arg in "$@"; do
  case "$arg" in
    --dry-run)   DRY_RUN=1 ;;
    --skip-build) SKIP_BUILD=1 ;;
    --skip-deps) SKIP_DEPS=1 ;;
    --force)     FORCE=1 ;;
    --setup-key) ACTION=setup_key ;;
    --rollback)  ACTION=rollback ;;                 # uses latest backup
    --rollback=*) ACTION=rollback; ROLLBACK_FILE="${arg#*=}" ;;
    --host=*)    DEPLOY_HOST="${arg#*=}" ;;
    --port=*)    DEPLOY_PORT="${arg#*=}" ;;
    --user=*)    DEPLOY_USER="${arg#*=}" ;;
    -h|--help)   sed -n '3,32p' "$0"; exit 0 ;;
    *) die "unknown argument: $arg (see --help)" ;;
  esac
done

SSH_OPTS=(-o StrictHostKeyChecking=accept-new -o ConnectTimeout=15 -p "$DEPLOY_PORT")
SSH_DEST="$DEPLOY_USER@$DEPLOY_HOST"

# Run a script on the server via stdin (avoids quoting pain). Dies on failure.
remote_exec() {
  if [ "$DRY_RUN" -eq 1 ]; then
    echo "$1" | sed 's/^/  [remote] /'
    return 0
  fi
  echo "$1" | ssh "${SSH_OPTS[@]}" "$SSH_DEST" 'bash -s' || die "remote command failed"
}

# Rsync excludes: preserve server-runtime data and server-local customizations.
#  - agent/.env is the REAL server config (has API keys) — never overwrite with local.
#  - agent/src/tools/ocr/qwen_vision_ocr.py is a server-local custom tool, not in upstream.
#  - sessions/runs/.swarm/factor_results are live runtime data.
#  - .venv/venv stay on the server; pip install -e . updates them in place.
#  - reports/ + tools/*.py are developer-local scratch, not part of the app.
EXCLUDES=(
  --exclude='.git/'
  --exclude='.venv/'
  --exclude='venv/'
  --exclude='__pycache__/'
  --exclude='*.pyc'
  --exclude='.idea/'
  --exclude='.DS_Store'
  --exclude='agent/.env'
  --exclude='agent/.env.bak*'
  --exclude='agent/src/tools/ocr/qwen_vision_ocr.py'
  --exclude='agent/sessions/'
  --exclude='agent/runs/'
  --exclude='agent/.swarm/'
  --exclude='runs/'
  --exclude='factor_results/'
  --exclude='agent/vibe_trading_ai.egg-info/'
  --exclude='frontend/node_modules/'
  --exclude='reports/'
  --exclude='tools/financial_rigor.py'
  --exclude='tools/report_audit.py'
)

do_deploy() {
  # 0. Pre-flight: refuse to silently deploy uncommitted tracked changes.
  if [ "$FORCE" -eq 0 ]; then
    dirty="$(git status --porcelain --untracked-files=no)"
    if [ -n "$dirty" ]; then
      warn "Working tree has uncommitted TRACKED changes:"
      echo "$dirty"
      warn "Re-run with --force to deploy them anyway."
      exit 1
    fi
  fi

  # 1. Build frontend locally (server has no node/npm).
  if [ "$SKIP_BUILD" -eq 0 ]; then
    log "Building frontend (npm run build)..."
    ( cd "$ROOT/frontend" && npm run build ) || die "frontend build failed"
  fi

  # 2. Backup the current server code (excludes venv, which is rebuilt by pip).
  stamp="$(date +%Y%m%d-%H%M%S)"
  backup_path="$DEPLOY_BACKUP_DIR/vibe-trading-src-$stamp.tar.gz"
  log "Backing up server code → $backup_path"
  remote_exec "mkdir -p $DEPLOY_BACKUP_DIR && tar czf $backup_path --exclude=$DEPLOY_APP_DIR/venv -C /opt vibe-trading && ls -lh $backup_path"

  # 3. Sync the working tree to the server.
  log "Syncing code → $DEPLOY_APP_DIR"
  if [ "$DRY_RUN" -eq 1 ]; then
    rsync -az --delete --dry-run "${EXCLUDES[@]}" -e "ssh ${SSH_OPTS[*]}" "$ROOT/" "$SSH_DEST:$DEPLOY_APP_DIR/"
  else
    rsync -az --delete "${EXCLUDES[@]}" -e "ssh ${SSH_OPTS[*]}" "$ROOT/" "$SSH_DEST:$DEPLOY_APP_DIR/" || die "rsync failed"
  fi

  # 4. Normalize ownership to the service user.
  remote_exec "chown -R vibe:vibe $DEPLOY_APP_DIR"

  # 5. Update Python deps (server has internet; mirror avoids the slow official index).
  if [ "$SKIP_DEPS" -eq 0 ]; then
    log "Updating Python deps (pip install -e .)..."
    remote_exec "cd $DEPLOY_APP_DIR && su -s /bin/bash vibe -c 'venv/bin/pip install -e . -i $PIP_INDEX_URL --timeout 60 --retries 5'"
  fi

  # 6. Restart and wait for health (startup takes ~1 min on this box).
  log "Restarting $DEPLOY_SERVICE..."
  remote_exec "systemctl restart $DEPLOY_SERVICE"
  log "Waiting for health on port $DEPLOY_HTTP_PORT..."
  remote_exec "for i in \$(seq 1 40); do curl -sf http://127.0.0.1:$DEPLOY_HTTP_PORT/health && echo && break; sleep 3; done"
  remote_exec "$DEPLOY_APP_DIR/venv/bin/vibe-trading --version"
  log "Deploy complete."
}

do_rollback() {
  local backup="$ROLLBACK_FILE"
  if [ -z "$backup" ]; then
    if [ "$DRY_RUN" -eq 1 ]; then
      backup="$DEPLOY_BACKUP_DIR/vibe-trading-src-LATEST.tar.gz"
    else
      backup="$(ssh -o BatchMode=yes "${SSH_OPTS[@]}" "$SSH_DEST" "ls -t $DEPLOY_BACKUP_DIR/vibe-trading-src-*.tar.gz 2>/dev/null | head -1" | tr -d '\r')"
    fi
    [ -n "$backup" ] || die "no backup found in $DEPLOY_BACKUP_DIR"
  fi
  log "Rolling back to $backup"
  remote_exec "test -f '$backup'"
  remote_exec "cd /opt && tar xzf '$backup' && chown -R vibe:vibe vibe-trading && cd $DEPLOY_APP_DIR && su -s /bin/bash vibe -c 'venv/bin/pip install -e . -i $PIP_INDEX_URL --timeout 60 --retries 5' && systemctl restart $DEPLOY_SERVICE"
  log "Waiting for health on port $DEPLOY_HTTP_PORT..."
  remote_exec "for i in \$(seq 1 40); do curl -sf http://127.0.0.1:$DEPLOY_HTTP_PORT/health && echo && break; sleep 3; done"
  remote_exec "$DEPLOY_APP_DIR/venv/bin/vibe-trading --version"
  log "Rollback complete."
}

do_setup_key() {
  local pub="$HOME/.ssh/id_ed25519.pub"
  [ -f "$pub" ] || die "no key at $pub — generate one with: ssh-keygen -t ed25519"
  log "Copying $pub → $DEPLOY_HOST:/root/.ssh/authorized_keys (will prompt for the server password once)"
  ssh-copy-id "${SSH_OPTS[@]}" "$SSH_DEST" || die "ssh-copy-id failed"
  log "Verifying key-based auth..."
  ssh -o BatchMode=yes "${SSH_OPTS[@]}" "$SSH_DEST" 'echo KEY_AUTH_OK' || die "key auth not working"
  log "SSH key auth is set up. Future deploys need no password."
}

case "$ACTION" in
  deploy)    do_deploy ;;
  rollback)  do_rollback ;;
  setup_key) do_setup_key ;;
esac

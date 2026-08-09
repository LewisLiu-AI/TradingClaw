#!/usr/bin/env bash
#
# start-dev.sh — 前台启动本地前后端开发服务器(一条命令,实时看日志,按 Ctrl-C 一起停)。
#
# 与 scripts/dev(后台守护式,带 status/logs/restart 管理)互补;这个更适合
# "开一个终端直接跑起来写代码"。
#
# 用法:
#   ./scripts/start-dev.sh              # 启动前后端,前台运行
#   ./scripts/start-dev.sh --no-frontend   # 只起后端
#   ./scripts/start-dev.sh --no-backend    # 只起前端
#   ./scripts/start-dev.sh --build         # 先构建前端(生产模式,不启 Vite dev server)
#
# 环境变量:
#   BACKEND_PORT=8899   FRONTEND_PORT=5899   PYTHON_BIN(默认 .venv/bin/vibe-trading)
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STATE_DIR="$ROOT/.vibe-dev"
LOG_DIR="$STATE_DIR/logs"
mkdir -p "$LOG_DIR"

BACKEND_HOST="${BACKEND_HOST:-127.0.0.1}"
BACKEND_PORT="${BACKEND_PORT:-8899}"
FRONTEND_HOST="${FRONTEND_HOST:-127.0.0.1}"
FRONTEND_PORT="${FRONTEND_PORT:-5899}"
PYTHON_BIN="${PYTHON_BIN:-$ROOT/.venv/bin/vibe-trading}"

NO_BACKEND=0
NO_FRONTEND=0
BUILD=0
for arg in "$@"; do
  case "$arg" in
    --no-backend)  NO_BACKEND=1 ;;
    --no-frontend) NO_FRONTEND=1 ;;
    --build)       BUILD=1 ;;
    -h|--help)     sed -n '1,25p' "$0"; exit 0 ;;
    *) echo "unknown argument: $arg (see --help)" >&2; exit 2 ;;
  esac
done

[[ $NO_BACKEND -eq 1 && $NO_FRONTEND -eq 1 ]] && { echo "nothing to start" >&2; exit 1; }

# 前置检查:venv、node_modules、.env
if [[ $NO_BACKEND -eq 0 ]]; then
  if [[ ! -x "$PYTHON_BIN" ]]; then
    echo "缺少后端可执行文件: $PYTHON_BIN" >&2
    echo "请先: uv venv .venv --python 3.12 && uv pip install -e ." >&2
    exit 1
  fi
  if [[ ! -f "$ROOT/agent/.env" ]]; then
    cp "$ROOT/agent/.env.example" "$ROOT/agent/.env"
    echo "已从 .env.example 生成 agent/.env(记得填 LLM key)"
  fi
fi
if [[ $NO_FRONTEND -eq 0 && ! -d "$ROOT/frontend/node_modules" ]]; then
  echo "frontend/node_modules 不存在,先 npm install ..."
  ( cd "$ROOT/frontend" && npm install ) || exit 1
fi

BACKEND_LOG="$LOG_DIR/backend.log"
FRONTEND_LOG="$LOG_DIR/frontend.log"
PIDS=()

cleanup() {
  echo
  echo "Stopping services..."
  for p in "${PIDS[@]}"; do kill "$p" 2>/dev/null; done
  wait 2>/dev/null
  exit 0
}
trap cleanup INT TERM EXIT

# ---- 后端 ----
if [[ $NO_BACKEND -eq 0 ]]; then
  echo "Backend  → http://$BACKEND_HOST:$BACKEND_PORT  (log: $BACKEND_LOG)"
  ( cd "$ROOT" && exec "$PYTHON_BIN" serve --host "$BACKEND_HOST" --port "$BACKEND_PORT" ) >"$BACKEND_LOG" 2>&1 &
  PIDS+=($!)
  ( tail -n +1 -F "$BACKEND_LOG" | sed 's/^/[backend]  /' ) &
  PIDS+=($!)
fi

# ---- 前端 ----
if [[ $NO_FRONTEND -eq 0 ]]; then
  if [[ $BUILD -eq 1 ]]; then
    echo "Frontend → 构建产物(无 dev server)"
    ( cd "$ROOT/frontend" && npm run build ) >"$FRONTEND_LOG" 2>&1 &
    PIDS+=($!)
  else
    echo "Frontend → http://$FRONTEND_HOST:$FRONTEND_PORT  (log: $FRONTEND_LOG)"
    ( cd "$ROOT/frontend" && exec npm run dev -- --host "$FRONTEND_HOST" --port "$FRONTEND_PORT" ) >"$FRONTEND_LOG" 2>&1 &
    PIDS+=($!)
    ( tail -n +1 -F "$FRONTEND_LOG" | sed 's/^/[frontend] /' ) &
    PIDS+=($!)
  fi
fi

echo "按 Ctrl-C 一起停止。"
echo "API docs: http://$BACKEND_HOST:$BACKEND_PORT/docs"
wait

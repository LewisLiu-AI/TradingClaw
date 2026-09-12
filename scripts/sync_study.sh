#!/usr/bin/env bash
#
# sync_study.sh — 把某个 reports/<study> 目录同步到生产服务器。
#
# 为什么需要单独一个脚本：scripts/deploy.sh 的 rsync **排除了 reports/**。
# 这是有意为之 —— reports/star50_study 里有生产侧才会更新的数据（cron 每交易日追加
# star50_index.csv 等），若纳入 deploy 的 `--delete` 同步会被本地旧副本覆盖。
# 所以研究报告类内容必须走这个显式、无 --delete 的通道。
#
# Usage:
#   ./scripts/sync_study.sh 301526_swing_study          # 同步
#   ./scripts/sync_study.sh 301526_swing_study --dry-run
#   ./scripts/sync_study.sh --list                      # 列出可同步的 study
#
# Server defaults (override via env):
#   DEPLOY_HOST=47.100.42.183  DEPLOY_USER=root  DEPLOY_PORT=22
#   DEPLOY_APP_DIR=/opt/vibe-trading  DEPLOY_SERVICE_USER=vibe
set -uo pipefail

DEPLOY_HOST="${DEPLOY_HOST:-47.100.42.183}"
DEPLOY_USER="${DEPLOY_USER:-root}"
DEPLOY_PORT="${DEPLOY_PORT:-22}"
DEPLOY_APP_DIR="${DEPLOY_APP_DIR:-/opt/vibe-trading}"
DEPLOY_SERVICE_USER="${DEPLOY_SERVICE_USER:-vibe}"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SSH_OPTS=(-o StrictHostKeyChecking=accept-new -o ConnectTimeout=15 -p "$DEPLOY_PORT")
SSH_DEST="$DEPLOY_USER@$DEPLOY_HOST"

log()  { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31mFAIL\033[0m %s\n' "$*" >&2; exit 1; }

if [ "${1:-}" = "--list" ] || [ $# -eq 0 ]; then
  echo "可同步的 study:"
  for d in "$ROOT"/reports/*/; do [ -d "$d" ] && echo "  $(basename "$d")"; done
  [ "${1:-}" = "--list" ] && exit 0
  die "用法: $0 <study 名> [--dry-run]"
fi

STUDY="$1"
DRY_RUN=0
[ "${2:-}" = "--dry-run" ] && DRY_RUN=1
SRC="$ROOT/reports/$STUDY"
[ -d "$SRC" ] || die "本地不存在: $SRC"

log "同步 reports/$STUDY → $DEPLOY_APP_DIR/reports/$STUDY$([ $DRY_RUN -eq 1 ] && echo ' (dry-run)')"
# 不用 --delete: 生产侧可能有本地没有的产物(如运行期生成的 csv/json)
RSYNC_OPTS=(-az --exclude='__pycache__' --exclude='.DS_Store'
            --itemize-changes -e "ssh ${SSH_OPTS[*]}")
if [ "$DRY_RUN" -eq 1 ]; then
  rsync "${RSYNC_OPTS[@]}" --dry-run "$SRC/" "$SSH_DEST:$DEPLOY_APP_DIR/reports/$STUDY/" \
    | grep -vE '^\.[fd]\.\.\.\.og\.|^$' || true
  log "dry-run 结束(上方为需变更项; 空=已一致)"
  exit 0
fi

rsync "${RSYNC_OPTS[@]}" "$SRC/" "$SSH_DEST:$DEPLOY_APP_DIR/reports/$STUDY/" \
  | grep -vE '^\.[fd]\.\.\.\.og\.|^$' || true
ssh "${SSH_OPTS[@]}" "$SSH_DEST" "chown -R $DEPLOY_SERVICE_USER:$DEPLOY_SERVICE_USER '$DEPLOY_APP_DIR/reports/$STUDY'" \
  || die "chown 失败"
log "完成。注意: 修改 swing_strategy.py 等脚本后无需重启服务(不是技能, 不被缓存)。"

#!/bin/bash
# sync_local.sh — 从 G2532 板子拉取本地验证的订阅文件并推送到 GitHub
# 用法: bash sync_local.sh [adb序列号]
# 建议 cron: */7 * * * * cd /path/to/repo && bash sync_local.sh

set -euo pipefail

cd "$(dirname "$0")"

ADB_SERIAL="${1:-3aa022e9d252e0fb}"
LOCK_DIR="/tmp/free-proxy-sub-sync.lock"

# 防止并发运行（cron 周期短于一次同步耗时时会重入）；
# 超过 30 分钟的锁视为上次异常退出的残留，直接清掉
if [ -d "$LOCK_DIR" ] && [ -n "$(find "$LOCK_DIR" -maxdepth 0 -mmin +30 2>/dev/null)" ]; then
    echo "  ⚠️  清理过期锁 $LOCK_DIR"
    rmdir "$LOCK_DIR" 2>/dev/null || true
fi
if ! mkdir "$LOCK_DIR" 2>/dev/null; then
    echo "  ⚠️  另一个同步进程正在运行，退出"
    exit 0
fi
trap 'rmdir "$LOCK_DIR"' EXIT

echo "[$(date '+%Y-%m-%d %H:%M:%S')] 开始同步本地验证结果..."

# 1. 从板子拉取最新文件
rm -rf /tmp/localhub-dist
if ! adb -s "$ADB_SERIAL" pull /data/localhub/dist/ /tmp/localhub-dist/ > /dev/null 2>&1; then
    echo "  ⚠️  adb 拉取失败（板子离线？），跳过"
    exit 1
fi

# 2. 检查文件是否有效
if [ ! -s /tmp/localhub-dist/clash.yaml ]; then
    echo "  ⚠️  板子文件不可用，跳过"
    exit 1
fi

# 3. 先拉取最新仓库状态（失败要可见，且不能留下 rebase 半途状态卡死后续运行）
if ! git pull --rebase origin main; then
    git rebase --abort 2>/dev/null || true
    echo "  ❌ git pull --rebase 失败，已回退，需要人工处理"
    exit 1
fi

# 4. 复制到 dist/local/
mkdir -p dist/local
for f in clash.yaml clash-selected.yaml sub.b64 sub-selected.b64 sub.txt status.json; do
    if [ -f "/tmp/localhub-dist/$f" ]; then
        cp "/tmp/localhub-dist/$f" "dist/local/$f"
    fi
done

# 5. 检查是否有变化
if git diff --quiet dist/local/; then
    echo "  ℹ️  文件无变化，跳过提交"
    exit 0
fi

# 6. 提交并推送（板子/CI 都在推，冲突时重试）
git add dist/local/
git commit -m "sync: update local proxies from G2532 board [$(date '+%Y-%m-%d %H:%M')]"
for i in 1 2 3; do
    if git push origin main; then
        echo "  ✅ 同步完成，已推送到 GitHub"
        exit 0
    fi
    git pull --rebase origin main || true
    sleep 5
done
echo "  ❌ push 失败"
exit 1

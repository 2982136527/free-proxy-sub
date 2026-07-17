#!/bin/bash
# sync_local.sh — 从 G2532 板子拉取本地验证的订阅文件并推送到 GitHub
# 用法: bash sync_local.sh
# 建议 cron: */30 * * * * cd /path/to/repo && bash sync_local.sh

set -e

cd "$(dirname "$0")"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] 开始同步本地验证结果..."

# 1. 从板子拉取最新文件
adb -s 3aa022e9d252e0fb pull /data/localhub/dist/ /tmp/localhub-dist/ > /dev/null 2>&1

# 2. 检查文件是否有效
if [ ! -f /tmp/localhub-dist/clash.yaml ]; then
    echo "  ⚠️  板子文件不可用，跳过"
    exit 1
fi

# 3. 先拉取最新仓库状态
git pull --rebase origin main > /dev/null 2>&1

# 4. 复制到 dist/local/
mkdir -p dist/local
cp /tmp/localhub-dist/clash.yaml        dist/local/clash.yaml
cp /tmp/localhub-dist/clash-selected.yaml dist/local/clash-selected.yaml
cp /tmp/localhub-dist/sub.b64           dist/local/sub.b64
cp /tmp/localhub-dist/sub-selected.b64  dist/local/sub-selected.b64
cp /tmp/localhub-dist/sub.txt           dist/local/sub.txt
cp /tmp/localhub-dist/status.json       dist/local/status.json

# 5. 检查是否有变化
if git diff --quiet dist/local/; then
    echo "  ℹ️  文件无变化，跳过提交"
    exit 0
fi

# 6. 提交并推送
git add dist/local/
git commit -m "sync: update local proxies from G2532 board [$(date '+%Y-%m-%d %H:%M')]"
git push origin main

echo "  ✅ 同步完成，已推送到 GitHub"

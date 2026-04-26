#!/bin/bash
# 一键安装 git pre-commit hook
# 用法：bash scripts/install-hooks.sh

set -e

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
HOOK_SRC="$PROJECT_ROOT/scripts/git-hooks/pre-commit"
HOOK_DST="$PROJECT_ROOT/.git/hooks/pre-commit"

if [ ! -f "$HOOK_SRC" ]; then
  echo "❌ source hook 不存在: $HOOK_SRC"
  exit 1
fi

mkdir -p "$PROJECT_ROOT/.git/hooks"

# 备份已有 hook（如果有）
if [ -f "$HOOK_DST" ] && [ ! -L "$HOOK_DST" ]; then
  cp "$HOOK_DST" "$HOOK_DST.bak.$(date +%s)"
  echo "已备份已有 hook 到 $HOOK_DST.bak.<timestamp>"
fi

# 安装 symlink（这样以后改 source 自动生效）
ln -sfn "$HOOK_SRC" "$HOOK_DST"
chmod +x "$HOOK_SRC"

echo "✅ pre-commit hook 已安装: $HOOK_DST → $HOOK_SRC"
echo ""
echo "测试 hook："
echo "  echo 'test' >> docs/index.html"
echo "  git add docs/index.html"
echo "  git commit -m 'test'   # 应被拒绝"
echo "  git restore --staged docs/index.html && git restore docs/index.html"

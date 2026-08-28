#!/usr/bin/env bash
# =============================================================
#  Atour 亚朵比价 · 统一启动脚本
#  同时启动前端（Astro 起始页，端口 4321）与后端（Streamlit 结果页，端口 8501）
#  用法： bash start.sh
# =============================================================
set -e

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FRONTEND="$ROOT/frontend"
BACKEND="$ROOT/backend"

ASTRO_PORT="${ASTRO_PORT:-4321}"
STREAMLIT_PORT="${STREAMLIT_PORT:-8501}"

# 节点运行时：优先 NODE 环境变量 > WorkBuddy 托管版本（$HOME 拼接，不写死用户名）> PATH 中的 node
if [ -n "$NODE" ]; then
  NODE_BIN="$NODE"
else
  MANAGED_NODE="$HOME/.workbuddy/binaries/node/versions/22.22.2/node.exe"
  if [ -f "$MANAGED_NODE" ]; then
    NODE_BIN="$MANAGED_NODE"
  else
    NODE_BIN="node"
  fi
fi
NPM_BIN="$(dirname "$NODE_BIN")/node_modules/npm/bin/npm-cli.js"
if [ ! -f "$NPM_BIN" ]; then
  NPM_BIN="npm"
fi

echo "=================================================="
echo "  Atour 亚朵比价 - 一键启动"
echo "  前端(起始页):  http://localhost:$ASTRO_PORT"
echo "  后端(结果页):  http://localhost:$STREAMLIT_PORT"
echo "=================================================="

# 1) 前端：若无依赖则安装；若无构建产物则构建（构建的 safe-delete 清理告警非致命，不阻断）
if [ ! -d "$FRONTEND/node_modules" ]; then
  echo "[frontend] 安装依赖..."
  (cd "$FRONTEND" && "$NODE_BIN" "$NPM_BIN" install)
fi
if [ ! -d "$FRONTEND/dist" ]; then
  echo "[frontend] 构建 Astro..."
  (cd "$FRONTEND" && "$NODE_BIN" "$NPM_BIN" run build || true)
fi

echo "[frontend] 启动预览 (端口 $ASTRO_PORT)..."
(cd "$FRONTEND" && "$NODE_BIN" "$NPM_BIN" run preview -- --port "$ASTRO_PORT" --host) &
FRONT_PID=$!

# 2) 后端：若无 venv 则创建并装依赖
if [ ! -d "$BACKEND/.venv" ]; then
  echo "[backend] 创建 Python 虚拟环境..."
  PYTHON="$HOME/.workbuddy/binaries/python/versions/3.13.12/python.exe"
  [ -f "$PYTHON" ] || PYTHON="python"
  "$PYTHON" -m venv "$BACKEND/.venv"
  echo "[backend] 安装依赖..."
  "$BACKEND/.venv/Scripts/python.exe" -m pip install -r "$BACKEND/requirements.txt"
fi

echo "[backend] 启动 Streamlit (端口 $STREAMLIT_PORT)..."
(cd "$BACKEND" && ./.venv/Scripts/streamlit.exe run app.py --server.port "$STREAMLIT_PORT" --server.headless true) &
BACK_PID=$!

echo ""
echo "两个服务已启动："
echo "  起始页: http://localhost:$ASTRO_PORT   (pid $FRONT_PID)"
echo "  结果页: http://localhost:$STREAMLIT_PORT (pid $BACK_PID)"
echo "按 Ctrl+C 停止。"

trap "echo ''; echo '停止服务...'; kill $FRONT_PID $BACK_PID 2>/dev/null; exit 0" INT TERM

wait

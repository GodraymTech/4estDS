#!/usr/bin/env bash
set -euo pipefail

VERSION="${1:-}"
if [[ -z "$VERSION" ]]; then
  echo "用法: $0 <version> (例如: $0 v1.0.2)"
  exit 1
fi

# 统一版本前缀为 vX.Y.Z
if [[ "$VERSION" != v* ]]; then
  VERSION="v$VERSION"
fi

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RELEASE_ROOT="${RELEASE_ROOT:-$HOME/rays/release/4estds}"
TARGET_RELEASE="$RELEASE_ROOT/releases/$VERSION"
SHARED_DIR="$RELEASE_ROOT/shared"

echo "=========================================="
echo ">>> 开始构建 4estDS 制品发布: $VERSION"
echo "    源码目录: $PROJECT_ROOT"
echo "    发布目录: $TARGET_RELEASE"
echo "    共享数据: $SHARED_DIR"
echo "=========================================="

cd "$PROJECT_ROOT"

# 1. 编译前端生产静态包 (Vite Build)
echo ">>> [1/5] 编译前端 Web 生产资源 (pnpm build)..."
pnpm --prefix web build

# 2. 初始化发布与共享目录
echo ">>> [2/5] 初始化制品发布目录结构..."
mkdir -p "$TARGET_RELEASE"
mkdir -p "$SHARED_DIR/.4estDS/db"
mkdir -p "$SHARED_DIR/.4estDS/cache"
mkdir -p "$SHARED_DIR/.4estDS/tmp"
mkdir -p "$SHARED_DIR/.4estDS/outputs"
mkdir -p "$SHARED_DIR/.4estDS/pids"
mkdir -p "$SHARED_DIR/configs"
mkdir -p "$SHARED_DIR/logs"

# 链接共享模型库
if [[ ! -e "$SHARED_DIR/.4estDS/models" ]] && [[ -d "$PROJECT_ROOT/.4estDS/models" ]]; then
  echo "    关联共享模型库软链接..."
  ln -s "$PROJECT_ROOT/.4estDS/models" "$SHARED_DIR/.4estDS/models"
fi

# 初始化生产配置文件 (如果不存在)
if [[ ! -f "$SHARED_DIR/configs/default.yaml" ]]; then
  echo "    生成生产独立配置文件..."
  cp "$PROJECT_ROOT/configs/default.yaml" "$SHARED_DIR/configs/default.yaml"
fi

# 初始化生产环境专属私密配置 (.env，如高德 Key 等)
if [[ ! -f "$SHARED_DIR/.env" ]] && [[ -f "$PROJECT_ROOT/.env" ]]; then
  echo "    从开发环境初始化生产专属 .env 密钥配置..."
  cp "$PROJECT_ROOT/.env" "$SHARED_DIR/.env"
  chmod 600 "$SHARED_DIR/.env"
fi

# 3. 打包发布产物 (不含 .git、web/src、tests 等开发源码)
echo ">>> [3/5] 同步纯净制品文件..."
rm -rf "$TARGET_RELEASE/dist" "$TARGET_RELEASE/src" "$TARGET_RELEASE/configs"
cp -r "$PROJECT_ROOT/web/dist" "$TARGET_RELEASE/dist"
cp -r "$PROJECT_ROOT/src" "$TARGET_RELEASE/src"
cp -r "$PROJECT_ROOT/configs" "$TARGET_RELEASE/configs"
cp "$PROJECT_ROOT/pyproject.toml" "$TARGET_RELEASE/pyproject.toml"
cp "$PROJECT_ROOT/uv.lock" "$TARGET_RELEASE/uv.lock"
[[ -f "$PROJECT_ROOT/README.md" ]] && cp "$PROJECT_ROOT/README.md" "$TARGET_RELEASE/README.md"
# 建立数据与环境软链接，保证相对路径 (.4estDS/...) 与环境变量 (forestds_HOME / .env) 寻址一致
ln -sfn "$SHARED_DIR/.4estDS" "$TARGET_RELEASE/.4estDS"
[[ -f "$SHARED_DIR/.env" ]] && ln -sfn "$SHARED_DIR/.env" "$TARGET_RELEASE/.env"

# 记录版本元数据
cat > "$TARGET_RELEASE/version.txt" <<EOF
Version: $VERSION
Commit: $(git rev-parse HEAD 2>/dev/null || echo "unknown")
BuildDate: $(date -u +"%Y-%m-%dT%H:%M:%SZ")
Builder: $(whoami)@$(hostname)
EOF

# 4. 准备生产虚拟环境 (安装运行必需依赖，无 dev 依赖)
echo ">>> [4/5] 同步生产 Python 运行环境 (uv sync --no-dev --all-extras)..."
cd "$TARGET_RELEASE"
uv sync --no-dev --all-extras

# 5. 生成生产专用控制脚本 ctl.sh 并完成软链接切换
echo ">>> [5/5] 生成控制脚本并原子切换激活版本..."
cat > "$RELEASE_ROOT/ctl.sh" <<'CTL_EOF'
#!/usr/bin/env bash
set -euo pipefail
trap '' HUP

BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CURRENT_APP="$BASE_DIR/current"
SHARED_DIR="$BASE_DIR/shared"

if [[ ! -d "$CURRENT_APP" ]]; then
  echo "错误: 未找到激活的发布版本 ($CURRENT_APP)"
  exit 1
fi

PORT_API="${PORT_API:-8000}"
export forestds_HOME="$SHARED_DIR/.4estDS"
export FORESTDS_STATIC_DIR="$CURRENT_APP/dist"
export ENV_MODE="prod"
export REDIS_URL="${REDIS_URL:-redis://localhost:6379/0}"

PID_DIR="$forestds_HOME/pids"
LOG_DIR="$SHARED_DIR/logs"
mkdir -p "$PID_DIR" "$LOG_DIR"

REDIS_PID_FILE="$PID_DIR/redis.pid"
BACKEND_PID_FILE="$PID_DIR/backend.pid"
WORKER_PID_FILE="$PID_DIR/worker.pid"

is_running() {
  local pid_file=$1
  local expected_keyword=${2:-}
  if [[ -f "$pid_file" ]]; then
    local pid
    pid=$(cat "$pid_file" 2>/dev/null || true)
    if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
      if [[ -n "$expected_keyword" ]]; then
        local cmdline
        cmdline=$(tr '\0' ' ' <"/proc/$pid/cmdline" 2>/dev/null || true)
        if [[ "$cmdline" != *"$expected_keyword"* ]]; then
          rm -f "$pid_file"
          return 1
        fi
      fi
      return 0
    fi
    rm -f "$pid_file"
  fi
  return 1
}

port_listening() {
  local port=$1
  ss -ltn 2>/dev/null | grep -qE ":$port[[:space:]]"
}

port_pids() {
  local port=$1
  ss -ltnp "sport = :$port" 2>/dev/null \
    | sed -nE 's/.*pid=([0-9]+).*/\1/p' \
    | sort -u
}

start_redis() {
  if is_running "$REDIS_PID_FILE" "redis-server" || port_listening 6379; then
    echo "Redis 已在运行中。"
    return
  fi
  if ! command -v redis-server >/dev/null 2>&1; then
    echo "缺少命令: redis-server"
    exit 1
  fi
  echo "正在启动生产 Redis..."
  nohup redis-server --bind 127.0.0.1 --port 6379 --save "" --appendonly no </dev/null >"$LOG_DIR/redis.log" 2>&1 &
  local pid=$!
  echo $pid >"$REDIS_PID_FILE"
  disown $pid 2>/dev/null || true
  sleep 0.5
  echo "Redis 已启动，PID: $pid"
}

start_worker() {
  if is_running "$WORKER_PID_FILE" "dramatiq"; then
    echo "生产 Worker 已在运行中。"
    return
  fi
  rm -f "$WORKER_PID_FILE"
  echo "正在启动 4estDS 生产 Worker (消费 DB 0 队列)..."
  cd "$CURRENT_APP"
  nohup env OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 REDIS_URL="$REDIS_URL" forestds_HOME="$forestds_HOME" .venv/bin/python3 -m dramatiq forestds.worker.actors --queues gpu review_gpu default --processes 1 --threads 1 </dev/null >>"$LOG_DIR/worker.log" 2>&1 &
  local pid=$!
  echo "$pid" >"$WORKER_PID_FILE"
  disown "$pid" 2>/dev/null || true
  sleep 0.8
  if is_running "$WORKER_PID_FILE" "dramatiq"; then
    echo "生产 Worker 已成功启动，PID: $pid (日志: $LOG_DIR/worker.log)"
  else
    echo "生产 Worker 已在启动中，PID: $pid"
  fi
}

start_app() {
  if port_listening "$PORT_API"; then
    echo "生产服务已在运行中 (端口 $PORT_API)。"
    return
  fi
  rm -f "$BACKEND_PID_FILE"
  echo "正在启动 4estDS 生产服务 (端口 $PORT_API，托管静态前端与 API)..."
  cd "$CURRENT_APP"
  setsid nohup env PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PORT_API="$PORT_API" ENV_MODE="prod" forestds_HOME="$forestds_HOME" FORESTDS_STATIC_DIR="$FORESTDS_STATIC_DIR" REDIS_URL="$REDIS_URL" .venv/bin/python3 -m uvicorn forestds.api.main:app --host 0.0.0.0 --port "$PORT_API" </dev/null >>"$LOG_DIR/backend.log" 2>&1 &
  local pid=$!
  disown -a 2>/dev/null || true
  sleep 1.2
  local pids
  pids=$(port_pids "$PORT_API" || echo "$pid")
  echo "$pids" >"$BACKEND_PID_FILE"
  if port_listening "$PORT_API"; then
    echo "生产服务已成功启动，PID: $pids (日志: $LOG_DIR/backend.log)"
  else
    echo "生产服务已在启动中，PID: $pids"
  fi
}

stop_one() {
  local name=$1
  local pid_file=$2
  local expected_keyword=${3:-}
  if ! is_running "$pid_file" "$expected_keyword"; then
    return 1
  fi
  local pid
  pid=$(cat "$pid_file")
  echo "正在停止 $name (PID: $pid)..."
  pkill -P "$pid" 2>/dev/null || true
  kill "$pid" 2>/dev/null || true
  sleep 0.3
  kill -9 "$pid" 2>/dev/null || true
  rm -f "$pid_file"
  return 0
}

stop_services() {
  echo ">>> 停止 4estDS 生产服务"
  stop_one "生产后端服务 ($PORT_API)" "$BACKEND_PID_FILE" "uvicorn" || true
  local pids
  pids=$(port_pids "$PORT_API" || true)
  if [[ -n "$pids" ]]; then
    while read -r p; do
      [[ -n "$p" ]] || continue
      kill -9 "$p" 2>/dev/null || true
    done <<< "$pids"
  fi
  rm -f "$BACKEND_PID_FILE"

  stop_one "生产推理 Worker" "$WORKER_PID_FILE" "dramatiq" || true
  pkill -f "$CURRENT_APP/.*dramatiq" 2>/dev/null || true
  rm -f "$WORKER_PID_FILE"

  echo "生产服务已停止。"
}

status_services() {
  echo "=== 4estDS 生产环境状态 [版本: $(cat "$CURRENT_APP/version.txt" 2>/dev/null | grep Version || echo "未知")] ==="
  echo "  应用主路径: $CURRENT_APP"
  echo "  共享数据:   $forestds_HOME"
  if port_listening 6379; then
    echo "  Redis:     运行中 (端口 6379)"
  else
    echo "  Redis:     已停止"
  fi
  if port_listening "$PORT_API"; then
    local pids
    pids=$(port_pids "$PORT_API" || echo "未知")
    echo "  Web & API: 运行中 (端口 $PORT_API, PID: $pids)"
    echo "    入口地址: http://127.0.0.1:$PORT_API"
  elif is_running "$BACKEND_PID_FILE" "uvicorn"; then
    echo "  Web & API: 启动中 (PID: $(cat "$BACKEND_PID_FILE"))"
  else
    echo "  Web & API: 已停止"
  fi
  if is_running "$WORKER_PID_FILE" "dramatiq"; then
    echo "  Worker:    运行中 (PID: $(cat "$WORKER_PID_FILE"))"
  else
    echo "  Worker:    已停止"
  fi
}

case "${1:-}" in
  start|on)
    start_redis
    start_worker
    start_app
    disown -a 2>/dev/null || true
    ;;
  stop|off)
    stop_services
    ;;
  restart)
    stop_services
    sleep 1
    start_redis
    start_worker
    start_app
    ;;
  status)
    status_services
    ;;
  *)
    echo "用法: $0 {start|stop|restart|status}"
    exit 1
    ;;
esac
CTL_EOF
chmod +x "$RELEASE_ROOT/ctl.sh"

# 原子软链接切换
ln -sfn "$TARGET_RELEASE" "$RELEASE_ROOT/current"

echo "=========================================="
echo ">>> 发布成功！已激活版本: $VERSION"
echo "    控制脚本: $RELEASE_ROOT/ctl.sh"
echo "    启动生产: $RELEASE_ROOT/ctl.sh start"
echo "    查看状态: $RELEASE_ROOT/ctl.sh status"
echo "=========================================="

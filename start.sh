#!/usr/bin/env bash
set -euo pipefail
trap '' HUP

# 单机多环境配置 (根据运行路径智能感知默认环境身份)
if [[ -z "${ENV_MODE:-}" ]]; then
  if [[ "$PWD" == *"_prod"* ]] || [[ "$PWD" == *"/prod"* ]]; then
    ENV_MODE="prod"
  else
    ENV_MODE="dev"
  fi
fi

if [[ "$ENV_MODE" == "dev" ]]; then
  PORT_API="${PORT_API:-8001}"
  PORT_WEB="${PORT_WEB:-5174}"
  START_WORKER="${START_WORKER:-false}"
  ENV_LABEL="开发环境 (DEV)"
else
  PORT_API="${PORT_API:-8000}"
  PORT_WEB="${PORT_WEB:-5173}"
  START_WORKER="${START_WORKER:-true}"
  ENV_LABEL="生产环境 (PROD)"
fi

# 运行根目录与数据隔离
export forestds_HOME="${forestds_HOME:-$PWD/.4estDS}"
PID_DIR="$forestds_HOME/pids"
LOG_DIR="logs"

REDIS_PID_FILE="$PID_DIR/redis.pid"
WORKER_PID_FILE="$PID_DIR/worker.pid"
BACKEND_PID_FILE="$PID_DIR/backend.pid"
FRONTEND_PID_FILE="$PID_DIR/frontend.pid"

REDIS_URL="${REDIS_URL:-redis://localhost:6379/0}"
UV_CACHE_DIR="${UV_CACHE_DIR:-/tmp/forestds-uv-cache}"

mkdir -p "$PID_DIR" "$LOG_DIR" "$forestds_HOME"

if [[ ! -d ".venv" ]]; then
  echo ">>> 检测到未初始化虚拟环境，正在自动同步 (uv sync)..."
  uv sync
fi

trap '' HUP

is_running() {
  local pid_file=$1
  if [[ -f "$pid_file" ]]; then
    local pid
    pid=$(cat "$pid_file")
    if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
      return 0
    fi
    rm -f "$pid_file"
  fi
  return 1
}

require_command() {
  local name=$1
  if ! command -v "$name" >/dev/null 2>&1; then
    echo "缺少命令: $name"
    exit 1
  fi
}

port_pids() {
  local port=$1
  ss -ltnp "sport = :$port" 2>/dev/null \
    | sed -nE 's/.*pid=([0-9]+).*/\1/p' \
    | sort -u
}

port_listening() {
  local port=$1
  ss -ltn 2>/dev/null | grep -qE ":$port[[:space:]]"
}

worker_pids() {
  ps -eo pid=,args= | awk '/[d]ramatiq/ && /forestds[.]worker[.]actors/ {print $1}' | sort -u
}

stop_port() {
  local name=$1
  local port=$2
  local pids
  pids=$(port_pids "$port" || true)
  if [[ -n "$pids" ]]; then
    echo "正在停止占用 $port 的 $name: $pids"
    while read -r pid; do
      [[ -n "$pid" ]] || continue
      pkill -P "$pid" 2>/dev/null || true
      kill "$pid" 2>/dev/null || true
    done <<< "$pids"
    return 0
  fi

  if port_listening "$port" && command -v fuser >/dev/null 2>&1; then
    echo "正在停止占用 $port 的 $name..."
    fuser -k "${port}/tcp" >/dev/null 2>&1 || true
    return 0
  fi
  return 1
}

start_redis() {
  if is_running "$REDIS_PID_FILE" || port_listening 6379; then
    echo "Redis 已在运行中。"
    return
  fi

  require_command redis-server
  echo "正在启动 Redis..."
  nohup redis-server --bind 127.0.0.1 --port 6379 --save "" --appendonly no </dev/null >"$LOG_DIR/redis.log" 2>&1 &
  local pid=$!
  echo $pid >"$REDIS_PID_FILE"
  disown $pid 2>/dev/null || true
  sleep 0.5
  if ! is_running "$REDIS_PID_FILE"; then
    echo "Redis 启动失败，请查看 $LOG_DIR/redis.log"
    exit 1
  fi
  echo "Redis 已启动，PID: $(cat "$REDIS_PID_FILE") (日志输出到 $LOG_DIR/redis.log)"
}

start_worker() {
  if [[ "$START_WORKER" != "true" ]]; then
    echo "推理 Worker: [DEV 模式跳过独立启动，共享生产 GPU 队列与 Worker]"
    return
  fi

  local pids
  pids=$(worker_pids || true)
  if is_running "$WORKER_PID_FILE" || [[ -n "$pids" ]]; then
    echo "推理 Worker 已在运行中${pids:+ (PID: $pids)}。"
    return
  fi

  echo "正在启动推理 Worker..."
  nohup env OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 REDIS_URL="$REDIS_URL" forestds_HOME="$forestds_HOME" .venv/bin/dramatiq forestds.worker.actors --processes 1 --threads 1 </dev/null >"$LOG_DIR/worker.log" 2>&1 &
  local pid=$!
  echo $pid >"$WORKER_PID_FILE"
  disown $pid 2>/dev/null || true
  sleep 1.0
  pids=$(worker_pids || true)
  if ! is_running "$WORKER_PID_FILE" && [[ -z "$pids" ]]; then
    echo "推理 Worker 启动失败，请查看 $LOG_DIR/worker.log"
    exit 1
  fi
  echo "推理 Worker 已启动${pids:+，PID: $pids} (日志输出到 $LOG_DIR/worker.log)"
}

start_backend() {
  if port_listening "$PORT_API"; then
    echo "后端 API 服务已在运行中 (端口 $PORT_API)。"
    return
  fi
  rm -f "$BACKEND_PID_FILE"

  echo "正在启动后端 API 服务 [$ENV_LABEL: 端口 $PORT_API]..."
  setsid nohup env PYTHONUNBUFFERED=1 forestds_HOME="$forestds_HOME" REDIS_URL="$REDIS_URL" .venv/bin/python3 -m uvicorn forestds.api.main:app --host 0.0.0.0 --port "$PORT_API" </dev/null >"$LOG_DIR/backend.log" 2>&1 &
  local pid=$!
  echo $pid >"$BACKEND_PID_FILE"
  disown $pid 2>/dev/null || true
  sleep 1.0
  echo "后端 API 服务已启动，PID: $(cat "$BACKEND_PID_FILE" 2>/dev/null || echo "$pid") (日志输出到 $LOG_DIR/backend.log)"
}

start_frontend() {
  if port_listening "$PORT_WEB"; then
    echo "前端 Web 服务已在运行中 (端口 $PORT_WEB)。"
    return
  fi
  rm -f "$FRONTEND_PID_FILE"

  echo "正在启动前端 Web 服务 [$ENV_LABEL: 端口 $PORT_WEB]..."
  setsid nohup env CI=true PORT="$PORT_WEB" VITE_PORT="$PORT_WEB" VITE_API_TARGET="http://127.0.0.1:$PORT_API" pnpm --prefix web run dev </dev/null >"$LOG_DIR/frontend.log" 2>&1 &
  local pid=$!
  echo $pid >"$FRONTEND_PID_FILE"
  disown $pid 2>/dev/null || true
  sleep 1.0
  echo "前端 Web 服务已启动，PID: $(cat "$FRONTEND_PID_FILE" 2>/dev/null || echo "$pid") (日志输出到 $LOG_DIR/frontend.log)"
}

start_services() {
  echo ">>> 启动 4estDS $ENV_LABEL (数据路径: $forestds_HOME)"
  start_redis
  start_worker
  start_backend
  start_frontend

  disown -a 2>/dev/null || true

  echo "----------------------------------------"
  echo "$ENV_LABEL 服务入口："
  echo "  API: http://127.0.0.1:$PORT_API"
  echo "  Web: http://localhost:$PORT_WEB"
  echo "  数据库: $forestds_HOME/db/4estds.sqlite"
  echo "----------------------------------------"
}

stop_one() {
  local name=$1
  local pid_file=$2

  if ! is_running "$pid_file"; then
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

stop_redis() {
  if [[ "$ENV_MODE" == "prod" ]]; then
    if stop_one "Redis" "$REDIS_PID_FILE"; then
      return
    fi
    if command -v redis-cli >/dev/null 2>&1; then
      redis-cli -h 127.0.0.1 -p 6379 shutdown nosave >/dev/null 2>&1 || true
    fi
    stop_port "Redis" 6379 || echo "Redis 未在运行。"
  fi
}

stop_worker() {
  if [[ "$START_WORKER" == "true" ]]; then
    stop_one "推理 Worker" "$WORKER_PID_FILE" || true
    local pids
    pids=$(worker_pids || true)
    if [[ -n "$pids" ]]; then
      echo "正在清理推理 Worker: $pids"
      while read -r pid; do
        [[ -n "$pid" ]] || continue
        pkill -9 -P "$pid" 2>/dev/null || true
        kill -9 "$pid" 2>/dev/null || true
      done <<< "$pids"
    fi
    rm -f "$WORKER_PID_FILE"
  fi
}

stop_services() {
  echo ">>> 停止 4estDS $ENV_LABEL"
  stop_one "前端 Web 服务 ($PORT_WEB)" "$FRONTEND_PID_FILE" || stop_port "前端 Web 服务" "$PORT_WEB" || echo "前端 Web 服务 未在运行。"
  stop_one "后端 API 服务 ($PORT_API)" "$BACKEND_PID_FILE" || stop_port "后端 API 服务" "$PORT_API" || echo "后端 API 服务 未在运行。"
  stop_worker
  stop_redis
  rm -f "$FRONTEND_PID_FILE" "$BACKEND_PID_FILE" "$WORKER_PID_FILE"
}

status_port() {
  local name=$1
  local pid_file=$2
  local port=$3
  local pids
  pids=$(port_pids "$port" || true)

  if port_listening "$port"; then
    if is_running "$pid_file"; then
      echo "$name: 运行中 (PID: $(cat "$pid_file"), 端口 $port)"
    elif [[ -n "$pids" ]]; then
      echo "$name: 运行中 (端口 $port, PID: $pids)"
    else
      echo "$name: 运行中 (端口 $port)"
    fi
  elif is_running "$pid_file"; then
    echo "$name: 启动中 (PID: $(cat "$pid_file"))"
  else
    echo "$name: 已停止"
  fi
}

status_services() {
  echo "=== 4estDS $ENV_LABEL 状态 [数据: $forestds_HOME] ==="
  status_port "Redis" "$REDIS_PID_FILE" 6379
  local pids
  pids=$(worker_pids || true)
  if is_running "$WORKER_PID_FILE"; then
    echo "推理 Worker: 运行中 (PID: $(cat "$WORKER_PID_FILE"))"
  elif [[ -n "$pids" ]]; then
    echo "推理 Worker: 运行中 (PID: $pids)"
  else
    echo "推理 Worker: 已停止"
  fi
  status_port "后端 API 服务" "$BACKEND_PID_FILE" "$PORT_API"
  status_port "前端 Web 服务" "$FRONTEND_PID_FILE" "$PORT_WEB"
}

case "${1:-}" in
  start|on)
    start_services
    ;;
  stop|off)
    stop_services
    ;;
  status)
    status_services
    ;;
  restart)
    stop_services
    sleep 1
    start_services
    ;;
  *)
    echo "用法: $0 {start|on|stop|off|restart|status}"
    exit 1
    ;;
esac

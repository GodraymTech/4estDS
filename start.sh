#!/usr/bin/env bash
set -euo pipefail

# 统一存储 PID 在 ~/.4estDS/pids 目录下，避免污染工作区。
PID_DIR="$HOME/.4estDS/pids"
LOG_DIR="logs"

REDIS_PID_FILE="$PID_DIR/redis.pid"
WORKER_PID_FILE="$PID_DIR/worker.pid"
BACKEND_PID_FILE="$PID_DIR/backend.pid"
FRONTEND_PID_FILE="$PID_DIR/frontend.pid"

REDIS_URL="${REDIS_URL:-redis://localhost:6379/0}"
UV_CACHE_DIR="${UV_CACHE_DIR:-/tmp/forestds-uv-cache}"

mkdir -p "$PID_DIR" "$LOG_DIR"

is_running() {
  local pid_file=$1
  if [[ -f "$pid_file" ]]; then
    local pid
    pid=$(cat "$pid_file")
    if [[ -n "$pid" ]] && ps -p "$pid" >/dev/null 2>&1; then
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
  ss -ltn "sport = :$port" 2>/dev/null | grep -q LISTEN
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
  redis-server --bind 127.0.0.1 --port 6379 --save "" --appendonly no >"$LOG_DIR/redis.log" 2>&1 &
  echo $! >"$REDIS_PID_FILE"
  sleep 0.3
  if ! is_running "$REDIS_PID_FILE"; then
    echo "Redis 启动失败，请查看 $LOG_DIR/redis.log"
    exit 1
  fi
  echo "Redis 已启动，PID: $(cat "$REDIS_PID_FILE") (日志输出到 $LOG_DIR/redis.log)"
}

start_worker() {
  local pids
  pids=$(worker_pids || true)
  if is_running "$WORKER_PID_FILE" || [[ -n "$pids" ]]; then
    echo "推理 Worker 已在运行中${pids:+ (PID: $pids)}。"
    return
  fi

  echo "正在启动推理 Worker..."
  REDIS_URL="$REDIS_URL" uv --cache-dir "$UV_CACHE_DIR" run --frozen dramatiq forestds.worker.actors --processes 1 --threads 1 >"$LOG_DIR/worker.log" 2>&1 &
  echo $! >"$WORKER_PID_FILE"
  sleep 0.5
  pids=$(worker_pids || true)
  if ! is_running "$WORKER_PID_FILE" && [[ -z "$pids" ]]; then
    echo "推理 Worker 启动失败，请查看 $LOG_DIR/worker.log"
    exit 1
  fi
  echo "推理 Worker 已启动${pids:+，PID: $pids} (日志输出到 $LOG_DIR/worker.log)"
}

start_backend() {
  if is_running "$BACKEND_PID_FILE" || port_listening 8000; then
    echo "后端 API 服务已在运行中。"
    return
  fi

  echo "正在启动后端 API 服务..."
  uv --cache-dir "$UV_CACHE_DIR" run --frozen uvicorn forestds.api.main:app --reload --host 0.0.0.0 --port 8000 >"$LOG_DIR/backend.log" 2>&1 &
  echo $! >"$BACKEND_PID_FILE"
  echo "后端 API 服务已启动，PID: $(cat "$BACKEND_PID_FILE") (日志输出到 $LOG_DIR/backend.log)"
}

start_frontend() {
  if is_running "$FRONTEND_PID_FILE" || port_listening 5173; then
    echo "前端 Web 服务已在运行中。"
    return
  fi

  echo "正在启动前端 Web 服务..."
  (cd web && mise exec -- pnpm run dev) >"$LOG_DIR/frontend.log" 2>&1 &
  echo $! >"$FRONTEND_PID_FILE"
  echo "前端 Web 服务已启动，PID: $(cat "$FRONTEND_PID_FILE") (日志输出到 $LOG_DIR/frontend.log)"
}

start_services() {
  start_redis
  start_worker
  start_backend
  start_frontend

  echo "服务入口："
  echo "  API: http://127.0.0.1:8000"
  echo "  Web: http://localhost:5173"
  echo "  Redis: $REDIS_URL"
}

stop_one() {
  local name=$1
  local pid_file=$2

  if ! is_running "$pid_file"; then
    echo "$name PID 未记录或已停止。"
    return 1
  fi

  local pid
  pid=$(cat "$pid_file")
  echo "正在停止 $name (PID: $pid)..."
  pkill -P "$pid" 2>/dev/null || true
  kill "$pid" 2>/dev/null || true
  rm -f "$pid_file"
  return 0
}

stop_redis() {
  if stop_one "Redis" "$REDIS_PID_FILE"; then
    return
  fi
  if command -v redis-cli >/dev/null 2>&1; then
    redis-cli -h 127.0.0.1 -p 6379 shutdown nosave >/dev/null 2>&1 || true
  fi
  stop_port "Redis" 6379 || echo "Redis 未在运行。"
}

stop_worker() {
  if stop_one "推理 Worker" "$WORKER_PID_FILE"; then
    return
  fi
  local pids
  pids=$(worker_pids || true)
  if [[ -z "$pids" ]]; then
    echo "推理 Worker 未在运行。"
    return
  fi
  echo "正在停止推理 Worker: $pids"
  while read -r pid; do
    [[ -n "$pid" ]] || continue
    pkill -P "$pid" 2>/dev/null || true
    kill "$pid" 2>/dev/null || true
  done <<< "$pids"
}

stop_services() {
  stop_one "前端 Web 服务" "$FRONTEND_PID_FILE" || stop_port "前端 Web 服务" 5173 || echo "前端 Web 服务 未在运行。"
  stop_one "后端 API 服务" "$BACKEND_PID_FILE" || stop_port "后端 API 服务" 8000 || echo "后端 API 服务 未在运行。"
  stop_worker
  stop_redis
  rm -f "$FRONTEND_PID_FILE" "$BACKEND_PID_FILE" "$WORKER_PID_FILE" "$REDIS_PID_FILE"
}

status_port() {
  local name=$1
  local pid_file=$2
  local port=$3
  local pids
  pids=$(port_pids "$port" || true)

  if is_running "$pid_file"; then
    echo "$name: 运行中 (PID: $(cat "$pid_file"))"
  elif [[ -n "$pids" ]]; then
    echo "$name: 运行中 (端口 $port, PID: $pids)"
  elif port_listening "$port"; then
    echo "$name: 运行中 (端口 $port)"
  else
    echo "$name: 已停止"
  fi
}

status_services() {
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
  status_port "后端 API 服务" "$BACKEND_PID_FILE" 8000
  status_port "前端 Web 服务" "$FRONTEND_PID_FILE" 5173
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

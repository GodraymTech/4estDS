#!/bin/bash

# 统一存储 PID 在 ~/.4estDS/pids 目录下，避免污染工作区环境
PID_DIR="$HOME/.4estDS/pids"
BACKEND_PID_FILE="$PID_DIR/backend.pid"
FRONTEND_PID_FILE="$PID_DIR/frontend.pid"

mkdir -p "$PID_DIR"

is_running() {
    local pid_file=$1
    if [ -f "$pid_file" ]; then
        local pid=$(cat "$pid_file")
        if ps -p "$pid" > /dev/null 2>&1; then
            return 0 # 运行中
        fi
    fi
    return 1 # 未运行
}

start_services() {
    local backend_started=0
    local frontend_started=0

    # 1. 检查并启动后端
    if is_running "$BACKEND_PID_FILE"; then
        echo "后端 API 服务已在运行中 (PID: $(cat $BACKEND_PID_FILE))。"
    else
        echo "正在启动后端 API 服务..."
        mkdir -p logs
        uv run uvicorn forestds.api.main:app --reload --host 127.0.0.1 --port 8000 > logs/backend.log 2>&1 &
        echo $! > "$BACKEND_PID_FILE"
        echo "后端 API 服务已启动，PID: $! (日志输出到 logs/backend.log)"
        backend_started=1
    fi

    # 2. 检查并启动前端
    if is_running "$FRONTEND_PID_FILE"; then
        echo "前端 Web 服务已在运行中 (PID: $(cat $FRONTEND_PID_FILE))。"
    else
        echo "正在启动前端 Web 服务..."
        mkdir -p logs
        (cd web && mise exec -- pnpm run dev) > logs/frontend.log 2>&1 &
        echo $! > "$FRONTEND_PID_FILE"
        echo "前端 Web 服务已启动，PID: $! (日志输出到 logs/frontend.log)"
        frontend_started=1
    fi

    if [ $backend_started -eq 1 ] || [ $frontend_started -eq 1 ]; then
        echo "服务启动中，请稍候查看状态..."
        echo "后端 API: http://127.0.0.1:8000"
        echo "前端 Web: http://localhost:5173"
    fi
}

stop_services() {
    local stopped=0

    # 1. 停止前端
    if is_running "$FRONTEND_PID_FILE"; then
        local pid=$(cat "$FRONTEND_PID_FILE")
        echo "正在停止前端 Web 服务 (PID: $pid)..."
        # 杀掉进程及其子进程
        pkill -P "$pid" 2>/dev/null
        kill "$pid" 2>/dev/null
        rm -f "$FRONTEND_PID_FILE"
        stopped=1
    else
        echo "前端 Web 服务未在运行。"
    fi

    # 2. 停止后端
    if is_running "$BACKEND_PID_FILE"; then
        local pid=$(cat "$BACKEND_PID_FILE")
        echo "正在停止后端 API 服务 (PID: $pid)..."
        pkill -P "$pid" 2>/dev/null
        kill "$pid" 2>/dev/null
        rm -f "$BACKEND_PID_FILE"
        stopped=1
    else
        echo "后端 API 服务未在运行。"
    fi

    if [ $stopped -eq 1 ]; then
        echo "服务已成功停止。"
    else
        echo "没有检测到正在运行的服务。"
    fi
}

status_services() {
    if is_running "$BACKEND_PID_FILE"; then
        echo "后端 API 服务: 运行中 (PID: $(cat $BACKEND_PID_FILE))"
    else
        echo "后端 API 服务: 已停止"
    fi

    if is_running "$FRONTEND_PID_FILE"; then
        echo "前端 Web 服务: 运行中 (PID: $(cat $FRONTEND_PID_FILE))"
    else
        echo "前端 Web 服务: 已停止"
    fi
}

case "$1" in
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
        echo "使用方法: $0 {start|on|stop|off|status|restart}"
        exit 1
        ;;
esac

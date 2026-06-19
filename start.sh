#!/bin/bash
# DevTools 启动脚本
#
# 用法:
#   ./start.sh                 启动 Web 面板 (http://localhost:8000)
#   ./start.sh web             同上
#   ./start.sh web -p 9000     指定端口
#
#   ./start.sh svc             列出系统服务
#   ./start.sh svc start nginx 启动/停止/重启系统服务
#
#   ./start.sh mw              列出中间件
#   ./start.sh mw status nacos 查看中间件详情
#   ./start.sh mw start nacos  启动中间件
#   ./start.sh mw stop nacos   停止中间件
#   ./start.sh mw restart nacos 重启中间件
#
# 直接透传:
#   ./start.sh list            等同于 cli.py list
#   ./start.sh start <name>    等同于 cli.py start <name>

cd "$(dirname "$0")"

# 虚拟环境检查与创建
if [ ! -d "venv" ]; then
    echo ">>> 首次运行，正在创建虚拟环境..."
    python3 -m venv venv
    echo ">>> 安装依赖..."
    venv/bin/pip install -q -r requirements.txt
    echo ">>> 环境就绪"
fi

# 确保 httpx 已安装（测试用）
venv/bin/pip install -q httpx 2>/dev/null

# 命令路由
case "${1:-}" in
    "")
        echo -e "\033[1;34m  DevTools Web 面板\033[0m"
        echo "  地址: http://0.0.0.0:8000"
        echo "  按 Ctrl+C 停止"
        echo ""
        venv/bin/python main.py
        ;;
    web)
        shift
        venv/bin/python cli.py web "$@"
        ;;
    svc)
        shift
        if [ $# -eq 0 ]; then
            venv/bin/python cli.py list
        else
            venv/bin/python cli.py "$@"
        fi
        ;;
    mw)
        shift
        if [ $# -eq 0 ]; then
            venv/bin/python cli.py mw list
        else
            venv/bin/python cli.py mw "$@"
        fi
        ;;
    *)
        venv/bin/python cli.py "$@"
        ;;
esac

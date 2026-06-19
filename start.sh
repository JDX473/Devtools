#!/bin/bash
# DevTools 启动脚本
# 用法: ./start.sh          -- 启动 Web 面板
#       ./start.sh web      -- 同上
#       ./start.sh list     -- 列出服务
#       ./start.sh status <name>  -- 查看状态
#       ./start.sh start <name>   -- 启动服务
#       ./start.sh stop <name>    -- 停止服务
#       ./start.sh restart <name> -- 重启服务

cd "$(dirname "$0")"

# 如果 venv 不存在则自动创建
if [ ! -d "venv" ]; then
    echo ">>> 首次运行，正在创建虚拟环境..."
    python3 -m venv venv
    echo ">>> 安装依赖..."
    venv/bin/pip install -r requirements.txt
fi

# 执行命令
if [ $# -eq 0 ]; then
    # 默认启动 Web 面板
    venv/bin/python main.py
else
    venv/bin/python cli.py "$@"
fi

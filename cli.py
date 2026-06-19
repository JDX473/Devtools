#!/usr/bin/env python3
"""
DevTools CLI — 命令行服务管理工具

用法：
  python cli.py list             列出所有服务
  python cli.py list --search nginx  搜索服务
  python cli.py status nginx     查看服务状态
  python cli.py start nginx      启动服务
  python cli.py stop nginx       停止服务
  python cli.py restart nginx    重启服务
  python cli.py enable nginx     设为开机自启
  python cli.py disable nginx    取消开机自启
  python cli.py web              启动 Web 面板
"""

import argparse
import sys
import service_manager as sm


def cmd_list(args):
    user_only = not args.all
    services = sm.list_services(
        filter_pattern=args.search if args.search else None,
        user_only=user_only,
    )
    if not services:
        print("未发现任何服务（可能不在 Linux 环境，或没有 systemd 服务）")
        return

    print(f"{'状态':<10} {'服务名':<36} {'自启':<10} {'PID':<8} 描述")
    print("-" * 100)
    for s in services:
        active = s.active_state.value
        sub = s.sub_state.value
        enabled = s.unit_file_state or "--"
        pid = str(s.pid) if s.pid else "--"
        desc = s.description[:50] if s.description else ""

        # 简洁的状态显示
        if s.sub_state.value == "running":
            status = f"● {sub}"
        elif s.sub_state.value in ("failed",):
            status = f"✖ {sub}"
        elif s.sub_state.value in ("dead",):
            status = f"○ {sub}"
        else:
            status = f"  {sub}"

        print(f"{status:<10} {s.name:<36} {enabled:<10} {pid:<8} {desc}")

    print(f"\n共 {len(services)} 个服务")


def cmd_status(args):
    info = sm.get_service(args.name)
    if info is None:
        print(f"服务 {args.name} 未找到")
        sys.exit(1)

    print(f"服务名:    {info.name}")
    print(f"描述:      {info.description or '--'}")
    print(f"Load:      {info.load_state}")
    print(f"Active:    {info.active_state.value}")
    print(f"Sub:       {info.sub_state.value}")
    print(f"开机自启:  {info.unit_file_state or '--'}")
    print(f"PID:       {info.pid or '--'}")
    print(f"是否运行:  {'是' if info.is_running else '否'}")


def cmd_start(args):
    result = sm.start_service(args.name)
    print(result.message)
    if not result.success:
        sys.exit(1)


def cmd_stop(args):
    result = sm.stop_service(args.name)
    print(result.message)
    if not result.success:
        sys.exit(1)


def cmd_restart(args):
    result = sm.restart_service(args.name)
    print(result.message)
    if not result.success:
        sys.exit(1)


def cmd_enable(args):
    result = sm.enable_service(args.name)
    print(result.message)
    if not result.success:
        sys.exit(1)


def cmd_disable(args):
    result = sm.disable_service(args.name)
    print(result.message)
    if not result.success:
        sys.exit(1)


def cmd_web(args):
    """启动 Web 管理面板"""
    import uvicorn
    from main import app

    port = args.port or 8000
    host = args.host or "0.0.0.0"

    print(f"DevTools Web 面板启动中...")
    print(f"  地址: http://{host}:{port}")
    print(f"  按 Ctrl+C 停止")
    uvicorn.run(app, host=host, port=port, log_level="info")


def main():
    parser = argparse.ArgumentParser(
        description="DevTools — 服务管理工具",
        prog="devtools",
    )
    subparsers = parser.add_subparsers(dest="command", help="可用命令")

    # list
    p_list = subparsers.add_parser("list", help="列出服务（默认只显示用户服务）")
    p_list.add_argument("--search", "-s", type=str, help="按名称搜索")
    p_list.add_argument("--all", "-a", action="store_true", help="显示所有服务（包括系统内部服务）")

    # status
    p_status = subparsers.add_parser("status", help="查看服务状态")
    p_status.add_argument("name", type=str, help="服务名")

    # start
    p_start = subparsers.add_parser("start", help="启动服务")
    p_start.add_argument("name", type=str, help="服务名")

    # stop
    p_stop = subparsers.add_parser("stop", help="停止服务")
    p_stop.add_argument("name", type=str, help="服务名")

    # restart
    p_restart = subparsers.add_parser("restart", help="重启服务")
    p_restart.add_argument("name", type=str, help="服务名")

    # enable
    p_enable = subparsers.add_parser("enable", help="设为开机自启")
    p_enable.add_argument("name", type=str, help="服务名")

    # disable
    p_disable = subparsers.add_parser("disable", help="取消开机自启")
    p_disable.add_argument("name", type=str, help="服务名")

    # web
    p_web = subparsers.add_parser("web", help="启动 Web 管理面板")
    p_web.add_argument("--port", "-p", type=int, default=8000, help="监听端口 (默认 8000)")
    p_web.add_argument("--host", type=str, default="0.0.0.0", help="监听地址 (默认 0.0.0.0)")

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(0)

    commands = {
        "list": cmd_list,
        "status": cmd_status,
        "start": cmd_start,
        "stop": cmd_stop,
        "restart": cmd_restart,
        "enable": cmd_enable,
        "disable": cmd_disable,
        "web": cmd_web,
    }

    commands[args.command](args)


if __name__ == "__main__":
    main()

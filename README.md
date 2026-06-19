# DevTools

轻量级服务管理与 CI/CD 面板。基于 FastAPI + systemd，无需 Docker。

## 功能

- **服务发现** — 自动列出服务器上所有 systemd 服务
- **状态查看** — 实时显示服务运行状态、PID、开机自启配置
- **服务控制** — 启动 / 停止 / 重启服务
- **开机自启** — 启用 / 禁用服务的开机自启
- **Web 面板** — 浏览器访问的仪表盘，支持搜索过滤
- **CLI 工具** — 命令行直接管理服务

## 快速开始

### 环境要求

- Python 3.10+
- Linux（使用 systemd）
- 管理服务需要 root 或 sudo 权限

### 安装

```bash
git clone https://github.com/JDX473/Devtools.git
cd Devtools
pip install -r requirements.txt
```

### 启动 Web 面板

```bash
# 方式 1：直接启动（推荐开发时用）
python main.py

# 方式 2：通过 CLI
python cli.py web

# 方式 3：指定端口和地址
python cli.py web --port 9090 --host 0.0.0.0
```

然后在浏览器打开 `http://<服务器IP>:8000`

### 命令行使用

```bash
# 列出所有服务
python cli.py list

# 搜索服务
python cli.py list --search nginx

# 查看服务详情
python cli.py status nginx

# 启动 / 停止 / 重启
python cli.py start nginx
python cli.py stop nginx
python cli.py restart nginx

# 开机自启
python cli.py enable nginx
python cli.py disable nginx
```

### 生产环境部署

推荐用 systemd 管理 DevTools 自身：

```ini
# /etc/systemd/system/devtools.service
[Unit]
Description=DevTools Service Manager
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/devtools
ExecStart=/usr/bin/python3 main.py
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now devtools
```

## API 文档

启动后访问 `http://<host>:8000/docs` 查看 Swagger 文档。

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/system` | 系统信息 |
| GET | `/api/services` | 服务列表（支持 `?search=` 过滤） |
| GET | `/api/services/{name}` | 服务详情 |
| POST | `/api/services/{name}/start` | 启动 |
| POST | `/api/services/{name}/stop` | 停止 |
| POST | `/api/services/{name}/restart` | 重启 |
| POST | `/api/services/{name}/enable` | 开机自启 |
| POST | `/api/services/{name}/disable` | 取消开机自启 |

## 项目结构

```
Devtools/
  main.py              # FastAPI 应用入口 + REST API
  service_manager.py   # systemd 封装（服务发现、操作）
  cli.py               # 命令行工具
  templates/
    index.html         # Web 仪表盘页面
  static/
    style.css          # 样式
    app.js             # 前端交互逻辑
  requirements.txt     # Python 依赖
```

## 技术栈

- **后端**: Python FastAPI
- **服务管理**: systemd (`systemctl`)
- **前端**: 原生 HTML/CSS/JS，无框架依赖

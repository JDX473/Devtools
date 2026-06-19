"""
DevTools — 轻量级 CI/CD 与服务管理面板
FastAPI 主入口
"""
from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from pathlib import Path

import service_manager as sm
import middleware as mw

app = FastAPI(
    title="DevTools",
    description="轻量级服务管理与 CI/CD 面板",
    version="0.1.0",
)

# ---- 静态文件 & 模板 ----

BASE_DIR = Path(__file__).parent
STATIC_DIR = BASE_DIR / "static"
TEMPLATES_DIR = BASE_DIR / "templates"

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ---- 页面 ----

@app.get("/", response_class=HTMLResponse)
async def dashboard():
    """主仪表盘页面"""
    template_path = TEMPLATES_DIR / "index.html"
    if template_path.exists():
        return template_path.read_text(encoding="utf-8")
    return HTMLResponse("<h1>DevTools</h1><p>模板文件未找到</p>", status_code=500)


# ---- API: 系统信息 ----

@app.get("/api/system")
async def system_info():
    """获取系统信息"""
    info = sm.get_system_info()
    try:
        mw_summary = mw.get_middleware_summary()
        info["middleware_count"] = mw_summary["total"]
        info["middleware_running"] = mw_summary["running"]
    except Exception:
        info["middleware_count"] = 0
        info["middleware_running"] = 0
    return info


# ---- API: 服务列表 ----

@app.get("/api/services")
async def list_services(
    search: str = Query(default="", description="按服务名搜索"),
    mode: str = Query(default="user", description="显示模式: user(用户服务) / all(全部)"),
):
    """列出服务，默认只显示用户安装的服务"""
    user_only = mode != "all"
    services = sm.list_services(
        filter_pattern=search if search else None,
        user_only=user_only,
    )
    return {
        "total": len(services),
        "services": [s.to_dict() for s in services],
        "platform": sm._is_linux(),
    }


# ---- API: 服务详情 ----

@app.get("/api/services/{name}")
async def get_service(name: str):
    """获取单个服务详情"""
    info = sm.get_service(name)
    if info is None:
        raise HTTPException(status_code=404, detail=f"服务 {name} 未找到")
    return info.to_dict()


# ---- API: 服务操作 ----

@app.post("/api/services/{name}/start")
async def start_service(name: str):
    info = sm.get_service(name)
    if info is None:
        raise HTTPException(status_code=404, detail=f"服务 {name} 未找到")
    result = sm.start_service(name)
    return result.to_dict()


@app.post("/api/services/{name}/stop")
async def stop_service(name: str):
    info = sm.get_service(name)
    if info is None:
        raise HTTPException(status_code=404, detail=f"服务 {name} 未找到")
    result = sm.stop_service(name)
    return result.to_dict()


@app.post("/api/services/{name}/restart")
async def restart_service(name: str):
    info = sm.get_service(name)
    if info is None:
        raise HTTPException(status_code=404, detail=f"服务 {name} 未找到")
    result = sm.restart_service(name)
    return result.to_dict()


@app.post("/api/services/{name}/enable")
async def enable_service(name: str):
    info = sm.get_service(name)
    if info is None:
        raise HTTPException(status_code=404, detail=f"服务 {name} 未找到")
    result = sm.enable_service(name)
    return result.to_dict()


@app.post("/api/services/{name}/disable")
async def disable_service(name: str):
    info = sm.get_service(name)
    if info is None:
        raise HTTPException(status_code=404, detail=f"服务 {name} 未找到")
    result = sm.disable_service(name)
    return result.to_dict()


# ---- API: 中间件列表 ----

@app.get("/api/middleware")
async def list_middleware(
    search: str = Query(default="", description="按名称搜索"),
    category: str = Query(default="", description="按分类过滤"),
):
    """列出所有检测到的中间件"""
    result = mw.list_middleware(
        search=search if search else None,
        category=category if category else None,
    )
    return {
        "total": len(result),
        "middleware": [m.to_dict() for m in result],
    }


@app.get("/api/middleware/summary")
async def middleware_summary():
    """中间件统计摘要"""
    return mw.get_middleware_summary()


@app.get("/api/middleware/{key}")
async def get_middleware(key: str):
    """获取单个中间件详情"""
    info = mw.get_middleware(key)
    if info is None:
        raise HTTPException(status_code=404, detail=f"中间件 {key} 未找到")
    return info.to_dict()


@app.post("/api/middleware/{key}/start")
async def start_middleware(key: str):
    """启动中间件"""
    result = mw.start_middleware(key)
    return result.to_dict()


@app.post("/api/middleware/{key}/stop")
async def stop_middleware(key: str):
    """停止中间件"""
    result = mw.stop_middleware(key)
    return result.to_dict()


@app.post("/api/middleware/{key}/restart")
async def restart_middleware(key: str):
    """重启中间件"""
    result = mw.restart_middleware(key)
    return result.to_dict()


# ---- 启动入口 ----

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

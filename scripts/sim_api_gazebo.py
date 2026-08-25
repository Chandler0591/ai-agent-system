"""
Gazebo 仿真专用轻量 API —— SIM_BACKEND=gazebo 的浏览器入口

与 app/main.py（全量 API）的区别：
- 只挂 sim 路由 + web 静态页，无数据库/Redis/embedding/认证等重依赖
- 供 ROS 2 容器内运行（rclpy 环境），浏览器 3D 视图 / SSE / 点击交互直连 Gazebo
- 单 worker 运行：GazeboBackend 是进程内单例，rclpy 不能多进程重复 init

启动（ROS 容器内，需已 source ROS + workspace 环境）：
    SIM_BACKEND=gazebo uvicorn scripts.sim_api_gazebo:app --host 0.0.0.0 --port 8001 --workers 1
一键编排：
    bash scripts/run_gazebo_api.sh
"""

import os

# 必须在导入 app.sim_api 之前固定后端（get_sim 懒加载时读取）
os.environ.setdefault("SIM_BACKEND", "gazebo")

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.sim_api import sim_router

app = FastAPI(title="AI 调度仿真 — Gazebo API", version="1.0")
app.include_router(sim_router, prefix="/api")

_WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "web")


@app.get("/")
@app.get("/index3d.html")
async def serve_3d():
    return FileResponse(os.path.join(_WEB_DIR, "index3d.html"))


@app.get("/sim.html")
async def serve_2d():
    return FileResponse(os.path.join(_WEB_DIR, "sim.html"))


@app.get("/intro.html")
async def serve_intro():
    return FileResponse(os.path.join(_WEB_DIR, "intro.html"))


if os.path.exists(_WEB_DIR):
    app.mount("/web", StaticFiles(directory=_WEB_DIR), name="web")

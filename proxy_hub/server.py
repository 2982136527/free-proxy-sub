"""FastAPI 服务器 — 本地调试 / Vercel 部署。"""
from pathlib import Path

from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware

from .config import load as load_config
from .storage import Storage
from .subscription import generate_clash_yaml, generate_json
from .validator import run_validation
from .crawler import crawl_github

config = load_config()
storage = Storage()

app = FastAPI(title="FreeProxyHub", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    return {"name": "FreeProxyHub", "version": "1.0.0"}


@app.get("/clash")
@app.get("/clash.yaml")
@app.get("/subscribe")
async def get_clash():
    """返回 Clash 订阅 YAML。"""
    yaml_str = generate_clash_yaml(config, storage)
    return Response(content=yaml_str, media_type="text/yaml; charset=utf-8")


@app.get("/clash.yaml")
async def get_clash_alt():
    yaml_str = generate_clash_yaml(config, storage)
    return Response(content=yaml_str, media_type="text/yaml; charset=utf-8")


@app.get("/api/nodes")
async def api_nodes():
    """JSON 节点列表。"""
    return generate_json(config, storage)


@app.get("/api/stats")
async def api_stats():
    return storage.stats()


@app.post("/api/trigger/crawl")
async def trigger_crawl():
    import asyncio
    result = await crawl_github(config, storage)
    return result


@app.post("/api/trigger/validate")
async def trigger_validate():
    alive = await run_validation(config, storage)
    return {"validated": alive}


@app.post("/api/trigger/full")
async def trigger_full():
    """全流程：爬取 → 解析 → 验证 → 生成。"""
    from . import main as hub_main
    result = await hub_main.run_cycle(config, storage)
    return result

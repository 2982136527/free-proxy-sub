"""FastAPI 服务器 — 本地订阅服务。"""
from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware

from .config import load as load_config
from .storage import Storage
from .subscription import generate_clash_yaml, generate_clash_selected, generate_json
from .uri_gen import generate_uris, generate_base64_subscription
from .validator import run_validation
from .crawler import crawl_github

config = load_config()
storage = Storage()

app = FastAPI(title="FreeProxyHub", version="1.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def root():
    return {
        "name": "FreeProxyHub",
        "version": "1.1.0",
        "endpoints": ["/clash.yaml", "/clash-selected.yaml", "/sub.b64",
                      "/sub-selected.b64", "/sub.txt", "/sub.json",
                      "/api/nodes", "/api/stats"],
    }


# 同步 def：FastAPI 自动放入线程池，避免生成大 YAML 阻塞事件循环

@app.get("/clash")
@app.get("/clash.yaml")
@app.get("/subscribe")
def get_clash():
    """返回 Clash 全量订阅 YAML。"""
    yaml_str = generate_clash_yaml(config, storage)
    return Response(content=yaml_str, media_type="text/yaml; charset=utf-8")


@app.get("/clash-selected.yaml")
def get_clash_selected():
    """返回 Clash 精选订阅 YAML。"""
    yaml_str = generate_clash_selected(config, storage)
    return Response(content=yaml_str, media_type="text/yaml; charset=utf-8")


def _alive(limit_key: str = "max_proxies"):
    scfg = config.get("subscription", {})
    return storage.get_alive_proxies(limit=scfg.get(limit_key, 200))


@app.get("/sub.b64")
def get_sub_b64():
    """Base64 通用订阅（Shadowrocket / v2rayN）。"""
    return Response(content=generate_base64_subscription(_alive()),
                    media_type="text/plain; charset=utf-8")


@app.get("/sub-selected.b64")
def get_sub_selected_b64():
    scfg = config.get("subscription", {})
    count = scfg.get("selected_count", 30)
    return Response(content=generate_base64_subscription(_alive()[:count]),
                    media_type="text/plain; charset=utf-8")


@app.get("/sub.txt")
def get_sub_txt():
    """纯文本每行一个链接（调试用）。"""
    return Response(content="\n".join(generate_uris(_alive())),
                    media_type="text/plain; charset=utf-8")


@app.get("/sub.json")
@app.get("/api/nodes")
def api_nodes():
    """JSON 节点列表。"""
    return generate_json(config, storage)


@app.get("/api/stats")
def api_stats():
    return storage.stats()


@app.post("/api/trigger/crawl")
async def trigger_crawl():
    return await crawl_github(config, storage)


@app.post("/api/trigger/validate")
async def trigger_validate():
    alive = await run_validation(config, storage)
    return {"validated": alive}


@app.post("/api/trigger/full")
async def trigger_full():
    """全流程：爬取 → 解析 → 验证 → 生成。"""
    from . import main as hub_main
    return await hub_main.run_cycle(config, storage)

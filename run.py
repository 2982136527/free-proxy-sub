#!/usr/bin/env python3
"""本地运行模式 — 周期性爬取 + HTTP 订阅服务。"""
import asyncio
import logging
import threading
from pathlib import Path

import uvicorn

from proxy_hub.config import load as load_config
from proxy_hub.storage import Storage
from proxy_hub.main import run_cycle

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("run")


def scheduler_loop(cfg: dict, storage: Storage):
    """后台周期运行。"""
    import time

    crawl_interval = cfg.get("crawler", {}).get("interval_minutes", 30) * 60
    validate_interval = cfg.get("validator", {}).get("interval_minutes", 5) * 60

    last_crawl = 0.0
    last_validate = 0.0

    while True:
        now = time.time()

        if now - last_crawl >= crawl_interval:
            logger.info("=== 开始爬取周期 ===")
            try:
                result = run_cycle(cfg, storage)
                logger.info("爬取结果: %s", result)
            except Exception as e:
                logger.error("周期异常: %s", e)
            last_crawl = now

        if now - last_validate >= validate_interval and now - last_crawl < 60:
            # 仅在非爬取周期做快速验证
            from proxy_hub.validator import run_validation_sync
            alive = run_validation_sync(cfg, storage)
            logger.info("快速验证: %d 个存活", alive)
            last_validate = now

        time.sleep(30)


def main():
    cfg = load_config()
    storage = Storage()

    # 启动后台调度
    t = threading.Thread(
        target=scheduler_loop,
        args=(cfg, storage),
        daemon=True,
    )
    t.start()

    # 启动 FastAPI
    host = cfg.get("server", {}).get("host", "0.0.0.0")
    port = cfg.get("server", {}).get("port", 8000)
    logger.info("启动订阅服务器 http://%s:%s", host, port)
    logger.info("Clash 订阅地址: http://%s:%s/clash.yaml", host, port)

    uvicorn.run(
        "proxy_hub.server:app",
        host=host,
        port=port,
        log_level="info",
    )


if __name__ == "__main__":
    main()

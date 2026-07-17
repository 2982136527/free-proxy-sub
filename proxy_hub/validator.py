"""TCP 连通性验证器 — 并发对代理做 TCP Ping。"""
import asyncio
from typing import List, Dict

from .storage import Storage


async def _tcp_ping(host: str, port: int, timeout: float) -> tuple[bool, float]:
    """TCP 连接测试，返回 (存活, 延迟ms)。"""
    try:
        t0 = asyncio.get_event_loop().time()
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port),
            timeout=timeout,
        )
        latency = (asyncio.get_event_loop().time() - t0) * 1000
        writer.close()
        await writer.wait_closed()
        return True, round(latency, 1)
    except Exception:
        return False, 0.0


async def run_validation(config: dict, storage: Storage):
    """对需要验证的代理执行 TCP ping。"""
    vcfg = config.get("validator", {})
    concurrency = vcfg.get("concurrency", 50)
    timeout = vcfg.get("connect_timeout", 5)

    proxies = storage.get_proxies_for_validation(limit=300)
    if not proxies:
        return 0

    sem = asyncio.Semaphore(concurrency)

    async def check(p: dict):
        async with sem:
            alive, latency = await _tcp_ping(p["host"], p["port"], timeout)
            storage.update_proxy_status(p["id"], alive, latency)
        return alive

    results = await asyncio.gather(*[check(p) for p in proxies])
    alive_count = sum(1 for r in results if r)
    return alive_count


def run_validation_sync(config: dict, storage: Storage) -> int:
    """同步包装，方便 CLI 调用。"""
    return asyncio.run(run_validation(config, storage))

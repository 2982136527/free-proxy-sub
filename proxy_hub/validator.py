"""TCP 连通性验证器 — 并发对代理做 TCP Ping（粗筛，真实可用性由 real_check 复核）。"""
import asyncio
import concurrent.futures
import weakref
from typing import List, Dict

from .storage import Storage

_dns_executor_loops = weakref.WeakSet()


def _ensure_dns_executor(loop, workers: int):
    """每个事件循环只扩一次 DNS 线程池，避免长驻服务反复替换导致线程泄漏。"""
    if loop not in _dns_executor_loops:
        loop.set_default_executor(
            concurrent.futures.ThreadPoolExecutor(max_workers=workers))
        _dns_executor_loops.add(loop)


async def _tcp_ping(host: str, port: int, timeout: float) -> tuple[bool, float]:
    """TCP 连接测试，返回 (存活, 延迟ms)。"""
    writer = None
    try:
        t0 = asyncio.get_event_loop().time()
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port),
            timeout=timeout,
        )
        latency = (asyncio.get_event_loop().time() - t0) * 1000
        return True, round(latency, 1)
    except Exception:
        return False, 0.0
    finally:
        if writer is not None:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass


async def run_validation(config: dict, storage: Storage) -> int:
    """对需要验证的代理执行 TCP ping。返回本轮存活数。"""
    vcfg = config.get("validator", {})
    concurrency = vcfg.get("concurrency", 100)
    timeout = vcfg.get("connect_timeout", 5)
    batch = vcfg.get("max_batch", 0)  # 0 = 全部待验证节点
    cooldown = vcfg.get("recheck_minutes", 5)

    proxies = storage.get_proxies_for_validation(limit=batch,
                                                 cooldown_minutes=cooldown)
    # hysteria2 走 QUIC/UDP，TCP ping 会误杀，交给 real_check 判定
    proxies = [p for p in proxies if p["proxy_type"] != "hysteria2"]
    if not proxies:
        return 0

    # DNS 解析走默认线程池执行器，默认只有几个线程，会成为吞吐瓶颈
    _ensure_dns_executor(asyncio.get_running_loop(),
                         min(int(concurrency), 128))

    sem = asyncio.Semaphore(concurrency)

    async def check(p: dict):
        async with sem:
            alive, latency = await _tcp_ping(p["host"], p["port"], timeout)
            storage.update_proxy_status(p["id"], alive, latency)
        return alive

    results = await asyncio.gather(*[check(p) for p in proxies])
    return sum(1 for r in results if r)


def run_validation_sync(config: dict, storage: Storage) -> int:
    """同步包装，方便 CLI 调用。"""
    return asyncio.run(run_validation(config, storage))

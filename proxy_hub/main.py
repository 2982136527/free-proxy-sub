"""核心工作流：爬取 → 解析 → 验证 → 清理 → 输出。"""
import asyncio
import logging
from typing import Optional

from .config import load as load_config
from .storage import Storage
from .crawler import crawl_github
from .parser import fetch_and_parse
from .validator import run_validation
from .subscription import generate_clash_yaml, generate_json

logger = logging.getLogger("proxy_hub")


async def run_cycle(config: Optional[dict] = None,
                    storage: Optional[Storage] = None) -> dict:
    """执行一次完整周期。"""
    cfg = config or load_config()
    st = storage or Storage()

    # 1) 爬取
    logger.info("开始爬取 GitHub …")
    try:
        crawl_result = await crawl_github(cfg, st)
        logger.info("爬取完成: found=%s new=%s", crawl_result["found"], crawl_result["new"])
    except Exception as e:
        logger.error("爬取失败: %s", e)
        crawl_result = {"found": 0, "new": 0, "error": str(e)}

    # 2) 解析
    sources = st.get_sources()
    parsed_total = 0
    for src in sources:
        if not src["is_active"]:
            continue
        try:
            proxies = await fetch_and_parse(src["url"])
            if proxies:
                for p in proxies:
                    p["source_id"] = src["id"]
                    st.add_proxy(p)
                st.mark_source_ok(src["url"])
                parsed_total += len(proxies)
            else:
                st.mark_source_err(src["url"], "empty response or parse failed")
        except Exception as e:
            st.mark_source_err(src["url"], str(e))
    logger.info("解析完成: 新增/更新 %d 个节点", parsed_total)

    # 3) 验证
    logger.info("开始 TCP 连通性验证 …")
    try:
        alive = await run_validation(cfg, st)
        logger.info("验证完成: %d 个存活", alive)
    except Exception as e:
        logger.error("验证失败: %s", e)
        alive = 0

    # 4) 清理
    max_dead = cfg.get("validator", {}).get("max_dead_count", 3)
    st.cleanup_dead(max_dead)

    # 5) 输出统计
    stats = st.stats()
    logger.info("当前状态: total=%d alive=%d sources=%d",
                stats["total"], stats["alive"], stats["sources"])

    return {
        "crawl": crawl_result,
        "parsed": parsed_total,
        "alive": alive,
        "stats": stats,
    }


def run_cycle_sync(config: Optional[dict] = None,
                   storage: Optional[Storage] = None) -> dict:
    """同步包装。"""
    return asyncio.run(run_cycle(config, storage))

"""GitHub crawler — 并发爬取免费代理订阅链接。"""
import os
import re
import asyncio
import base64
from typing import Set, List

import aiohttp

from .storage import Storage

GITHUB_API = "https://api.github.com"

URL_PATTERN = re.compile(r"https?://[^\s\"'<>]+", re.IGNORECASE)

SUB_KEYWORDS = [
    "subscribe", "sub", "clash", "proxy", "node",
    "ss", "v2ray", "trojan", "config", "link",
]

# ── 内置已知免费代理订阅源（社区维护，尽量稳定）─────────────
# 这些是 GitHub 上知名的免费代理聚合 / 订阅链接分享项目
BUILTIN_SOURCES = [
    # Free proxy subscription aggregators (common community URLs)
    "https://raw.githubusercontent.com/mfuu/v2ray/master/v2ray",
    "https://raw.githubusercontent.com/ssrsub/ssr/master/v2ray",
    "https://raw.githubusercontent.com/Pawdroid/Free-servers/main/sub",
    "https://raw.githubusercontent.com/aiboboxx/v2rayfree/main/v2ray",
    "https://raw.githubusercontent.com/ripaojiedian/freenode/main/sub",
    "https://raw.githubusercontent.com/ts-sf/free/main/v2ray",
    "https://raw.githubusercontent.com/freefq/free/master/v2ray",
    "https://raw.githubusercontent.com/learnhard-cn/free_proxy_ss/main/free",
    "https://raw.githubusercontent.com/peasoft/NoMoreWalls/master/list.txt",
    "https://raw.githubusercontent.com/itsyebekhe/HiN-VPN/main/subscription/base64",
    "https://raw.githubusercontent.com/freebaProxy/freebaProxy/main/freeproxy.txt",
    "https://raw.githubusercontent.com/adiwzx/freenode/main/adisub.txt",
    "https://raw.githubusercontent.com/ssrsub/ssr/master/ssr",
    "https://raw.githubusercontent.com/ripaojiedian/freenode/main/",
    # Clash meta proxy providers
    "https://raw.githubusercontent.com/ermaozi01/free_clash_node/main/subscription/clash.yml",
    "https://raw.githubusercontent.com/anaer/Sub/main/clash.yaml",
    "https://raw.githubusercontent.com/openRunner/clash-freenode/main/clashnode.yml",
]

# ── 快捷向量查询：搜代码比搜通用关键词准得多 ────────────────
CODE_QUERIES = [
    # 搜索包含代理链接的文本文件
    'ss:// extension:txt',
    'vmess:// extension:txt',
    'trojan:// extension:txt',
    'ss:// extension:conf',
    # 搜索 Clash 配置文件
    'proxies: extension:yaml',
    'proxies: extension:yml',
    # 搜索 JSON 格式
    '"server":" extension:json',
    'free-proxy extension:txt',
]

REPO_QUERIES = [
    "free proxy subscription list",
    "v2ray subscription link",
    "clash node free",
    "proxy subscribe url",
    "free clash subscription",
    "机场 免费 订阅",
    "freesub clash v2ray",
    "free node proxy",
]


def _is_sub_url(url: str) -> bool:
    u = url.lower()
    if u.startswith(("ss://", "vmess://", "trojan://", "vless://", "hysteria2://", "hy2://")):
        return True
    if any(kw in u for kw in SUB_KEYWORDS):
        return True
    return any(u.endswith(ext) for ext in (".yaml", ".yml", ".txt", ".json", ".conf"))


async def _fetch(session: aiohttp.ClientSession, url: str, timeout=10) -> str | None:
    """GET 请求，返回文本内容或 None。"""
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
            if resp.status == 200:
                return await resp.text()
    except Exception:
        pass
    return None


async def seed_builtin_sources(storage: Storage) -> int:
    """将内置已知源写入数据库（不重复写入）。"""
    count = 0
    for url in BUILTIN_SOURCES:
        if storage.add_source(url, source_type="builtin"):
            count += 1
    return count


async def crawl_code(session: aiohttp.ClientSession, storage: Storage,
                     queries: List[str]) -> List[str]:
    """搜索 GitHub 代码，提取包含代理链接的文件 URL。"""
    found: Set[str] = set()
    sem = asyncio.Semaphore(3)  # 代码搜索并发限制

    async def search_one(query: str):
        async with sem:
            try:
                params = {"q": query, "per_page": 30}
                async with session.get(
                    f"{GITHUB_API}/search/code",
                    params=params,
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as resp:
                    if resp.status != 200:
                        return
                    data = await resp.json()
                    for item in data.get("items", []):
                        raw_url = item.get("html_url", "")
                        # Convert to raw URL
                        if "/blob/" in raw_url:
                            raw_url = raw_url.replace("/blob/", "/raw/")
                            found.add(raw_url)
            except Exception:
                pass

    await asyncio.gather(*[search_one(q) for q in queries], return_exceptions=True)

    count = 0
    for url in found:
        if storage.add_source(url, source_type="github_code"):
            count += 1
    print(f"  [crawler] code search: found {len(found)} files, {count} new")
    return list(found)


async def crawl_repos(session: aiohttp.ClientSession, storage: Storage,
                      queries: List[str]) -> int:
    """搜索 GitHub 仓库，从 README 提取订阅链接。"""
    found: Set[str] = set()
    sem = asyncio.Semaphore(5)  # 并发控制

    async def search_repos(query: str):
        async with sem:
            try:
                params = {"q": query, "sort": "updated", "per_page": 30}
                async with session.get(
                    f"{GITHUB_API}/search/repositories",
                    params=params,
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as resp:
                    if resp.status != 200:
                        return
                    data = await resp.json()

                # 并发读 README
                repos = data.get("items", [])
                async def read_repo(repo: dict):
                    full_name = repo.get("full_name", "")
                    text = f"{full_name} {repo.get('description','') or ''}"

                    readme_url = f"{GITHUB_API}/repos/{full_name}/readme"
                    readme_text = await _fetch(session, readme_url, timeout=8)
                    if readme_text:
                        try:
                            content = json.loads(readme_text).get("content", "")
                            decoded = base64.b64decode(content).decode("utf-8", errors="ignore")
                            text += "\n" + decoded
                        except Exception:
                            pass

                    for url in URL_PATTERN.findall(text):
                        if _is_sub_url(url):
                            found.add(url)

                await asyncio.gather(*[read_repo(r) for r in repos], return_exceptions=True)
            except Exception:
                pass

    await asyncio.gather(*[search_repos(q) for q in queries], return_exceptions=True)

    new = 0
    for url in found:
        if storage.add_source(url, source_type="github_repo"):
            new += 1
    print(f"  [crawler] repo search: found {len(found)} urls, {new} new")
    return new


import json  # noqa: needed above


async def crawl_github(config: dict, storage: Storage) -> dict:
    """执行一次完整爬取，带超时。"""
    token = config.get("github", {}).get("token", "") or os.environ.get("GITHUB_TOKEN", "")
    timeout_sec = 110  # 整体超时

    headers = {
        "User-Agent": "ProxyHub/1.0",
        "Accept": "application/vnd.github.v3+json",
    }
    if token:
        headers["Authorization"] = f"token {token}"

    # 1) 种子内置源
    seeded = await seed_builtin_sources(storage)
    print(f"  [crawler] seeded builtin: {seeded} new")

    async with aiohttp.ClientSession(headers=headers) as sess:
        tasks = [
            crawl_code(sess, storage, CODE_QUERIES),
            crawl_repos(sess, storage, REPO_QUERIES),
        ]
        done, pending = await asyncio.wait(
            asyncio.gather(*tasks, return_exceptions=True),
            timeout=timeout_sec,
        )

    # 统计
    total_sources = len(storage.get_sources())
    return {
        "found": total_sources,
        "new": seeded,
        "timed_out": len(pending) > 0,
    }

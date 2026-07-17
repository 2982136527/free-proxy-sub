"""GitHub crawler — 并发爬取免费代理订阅链接。"""
import os
import re
import asyncio
import json as _json
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

# ── 内置已知免费代理订阅源 ──────────────────────────
BUILTIN_SOURCES = [
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
    "https://raw.githubusercontent.com/ermaozi01/free_clash_node/main/subscription/clash.yml",
    "https://raw.githubusercontent.com/anaer/Sub/main/clash.yaml",
    "https://raw.githubusercontent.com/openRunner/clash-freenode/main/clashnode.yml",
]


def _is_sub_url(url: str) -> bool:
    u = url.lower()
    if u.startswith(("ss://", "vmess://", "trojan://", "vless://", "hysteria2://", "hy2://")):
        return True
    if any(kw in u for kw in SUB_KEYWORDS):
        return True
    return any(u.endswith(ext) for ext in (".yaml", ".yml", ".txt", ".json", ".conf"))


async def _fetch_text(session: aiohttp.ClientSession, url: str,
                      timeout=10) -> str | None:
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
            return await resp.text() if resp.status == 200 else None
    except Exception:
        return None


async def seed_builtin_sources(storage: Storage) -> int:
    count = 0
    for url in BUILTIN_SOURCES:
        if storage.add_source(url, source_type="builtin"):
            count += 1
    return count


async def crawl_github(config: dict, storage: Storage) -> dict:
    """执行一次完整爬取。"""
    token = config.get("github", {}).get("token", "") or os.environ.get("GITHUB_TOKEN", "")

    headers = {
        "User-Agent": "ProxyHub/1.0",
        "Accept": "application/vnd.github.v3+json",
    }
    if token:
        headers["Authorization"] = f"token {token}"

    # 1) 种子内置源（快、不出错）
    seeded = await seed_builtin_sources(storage)

    # 2) GitHub 搜索（带 90s 超时）
    found_code = 0
    found_repo = 0

    try:
        async with aiohttp.ClientSession(headers=headers) as sess:
            sem = asyncio.Semaphore(5)

            async def search_repos(query: str, page=1):
                nonlocal found_repo
                async with sem:
                    try:
                        async with sess.get(
                            f"{GITHUB_API}/search/repositories",
                            params={"q": query, "sort": "updated", "per_page": 10, "page": page},
                            timeout=aiohttp.ClientTimeout(total=15),
                        ) as resp:
                            if resp.status != 200:
                                return
                            data = await resp.json()

                        async def read_repo(repo: dict):
                            nonlocal found_repo
                            full = repo.get("full_name", "")
                            text = f"{full} {repo.get('description','') or ''}"
                            # README
                            try:
                                r = await _fetch_text(sess, f"{GITHUB_API}/repos/{full}/readme", 8)
                                if r:
                                    c = _json.loads(r).get("content", "")
                                    text += "\n" + base64.b64decode(c).decode("utf-8", errors="ignore")
                            except Exception:
                                pass
                            # 列出根目录文件
                            try:
                                r = await _fetch_text(sess, f"{GITHUB_API}/repos/{full}/contents", 8)
                                if r:
                                    for f in _json.loads(r):
                                        if f.get("type") == "file" and f["name"].endswith((".txt", ".yaml", ".yml", "json")):
                                            content = await _fetch_text(sess, f["download_url"], 10)
                                            if content:
                                                text += "\n" + content
                            except Exception:
                                pass

                            for url in URL_PATTERN.findall(text):
                                if _is_sub_url(url):
                                    if storage.add_source(url, source_type="github_repo"):
                                        found_repo += 1

                        await asyncio.gather(*[read_repo(r) for r in data.get("items", [])],
                                            return_exceptions=True)
                    except Exception:
                        pass

            queries = [
                "free proxy subscription list",
                "v2ray subscription link",
                "clash node free",
                "proxy subscribe url",
                "free clash subscription",
                "机场 免费 订阅",
                "free node proxy",
                "clash proxy list",
            ]

            tasks = [search_repos(q, 1) for q in queries]
            # 加超时：最多等 90s
            await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True),
                timeout=90,
            )
    except asyncio.TimeoutError:
        pass  # 超时了但没关系
    except Exception as e:
        print(f"  [crawler] GitHub search error: {e}")

    print(f"  [crawler] builtin={seeded} new, github_repo={found_repo} new")

    total = len(storage.get_sources())
    return {"found": total, "new": seeded + found_code + found_repo}

"""GitHub crawler — 搜索 GitHub 免费代理订阅链接。"""
import os
import re
import asyncio
import base64
from typing import Set

import aiohttp

from .storage import Storage

GITHUB_API = "https://api.github.com"

URL_PATTERN = re.compile(
    r'https?://[^\s"\'<>]+', re.IGNORECASE
)

SUB_KEYWORDS = [
    "subscribe", "sub", "clash", "proxy", "node",
    "ss", "v2ray", "trojan", "config", "link",
]


def _is_sub_url(url: str) -> bool:
    u = url.lower()
    # 直接是代理链接
    if u.startswith(("ss://", "vmess://", "trojan://", "vless://", "hysteria2://", "hy2://")):
        return True
    # 包含订阅关键词
    if any(kw in u for kw in SUB_KEYWORDS):
        return True
    # 常见文件后缀
    return any(u.endswith(ext) for ext in (".yaml", ".yml", ".txt", ".json"))


def _extract_urls(text: str) -> list[str]:
    return list(set(URL_PATTERN.findall(text)))


def _b64_decode_sub(text: str) -> list[str]:
    """尝试从 base64 编码的内容中解码出代理链接。"""
    # 匹配较长的 base64 字符串
    for match in re.finditer(r"[A-Za-z0-9+/=]{80,}", text):
        try:
            decoded = base64.b64decode(match.group()).decode("utf-8", errors="ignore")
            if "://" in decoded:
                return [line.strip() for line in decoded.splitlines() if "://" in line.strip()]
        except Exception:
            continue
    return []


async def crawl_github(config: dict, storage: Storage) -> dict:
    """执行一次 GitHub 爬取，返回 {found, new}。"""
    token = config.get("github", {}).get("token", "") or os.environ.get("GITHUB_TOKEN", "")
    queries = config.get("github", {}).get("search_queries", [])

    headers = {
        "User-Agent": "ProxyHub/1.0",
        "Accept": "application/vnd.github.v3+json",
    }
    if token:
        headers["Authorization"] = f"token {token}"

    found: Set[str] = set()

    async with aiohttp.ClientSession(headers=headers) as sess:
        for query in queries:
            # 搜索仓库
            for page in (1, 2):
                try:
                    async with sess.get(
                        f"{GITHUB_API}/search/repositories",
                        params={"q": query, "sort": "updated", "per_page": 50, "page": page},
                        timeout=aiohttp.ClientTimeout(total=20),
                    ) as resp:
                        if resp.status != 200:
                            if resp.status == 403:
                                break  # 限流
                            continue
                        data = await resp.json()
                        for repo in data.get("items", []):
                            full_name = repo.get("full_name", "")
                            desc = repo.get("description", "") or ""
                            text = f"{full_name} {desc}"

                            # 读 README
                            try:
                                async with sess.get(
                                    f"{GITHUB_API}/repos/{full_name}/readme",
                                    timeout=aiohttp.ClientTimeout(total=10),
                                ) as r_resp:
                                    if r_resp.status == 200:
                                        rdata = await r_resp.json()
                                        content = rdata.get("content", "")
                                        try:
                                            text += "\n" + base64.b64decode(content).decode("utf-8", errors="ignore")
                                        except Exception:
                                            pass
                            except Exception:
                                pass

                            for url in _extract_urls(text):
                                if _is_sub_url(url):
                                    found.add(url)

                            # 不要打太多请求
                            await asyncio.sleep(0.05)

                        if len(data.get("items", [])) < 50:
                            break
                except Exception:
                    break

            # 先简单 repo 搜索（code 搜索需要额外权限，容易限流）

    # 去重入库
    new = 0
    for url in found:
        if storage.add_source(url):
            new += 1

    return {"found": len(found), "new": new}

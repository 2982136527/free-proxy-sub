"""代理格式解析器 — 支持 Clash YAML / Base64 / SIP008 / 单链接。"""
import json
import base64
import re
from typing import List, Optional

import yaml
import aiohttp


def _b64decode(s: str) -> str:
    """Base64 解码，自动补全 padding。"""
    pad = 4 - len(s) % 4
    if pad != 4:
        s += "=" * pad
    try:
        return base64.b64decode(s).decode("utf-8", errors="ignore")
    except Exception:
        return ""


# ── 单链接解析 ─────────────────────────────────────────────

def parse_ss(link: str) -> Optional[dict]:
    """ss://base64(method:password)@host:port#name"""
    try:
        rest = link[5:]  # ss://
        if "@" in rest:
            user_b64, hp = rest.split("@", 1)
            user = _b64decode(user_b64)
            if not user:
                user = user_b64
            method, password = user.split(":", 1)
        else:
            raw = _b64decode(rest)
            if not raw:
                raw = rest
            method, rest2 = raw.split(":", 1)
            password, hp = rest2.rsplit("@", 1)

        name = ""
        if "#" in hp:
            hp, name = hp.split("#", 1)

        host, port_s = hp.rsplit(":", 1)
        port = int(port_s)
        return {
            "proxy_type": "ss",
            "name": name or f"SS-{host}:{port}",
            "host": host, "port": port,
            "cipher": method, "password": password,
            "raw_link": link,
        }
    except Exception:
        return None


def parse_vmess(link: str) -> Optional[dict]:
    """vmess://base64(JSON)"""
    try:
        raw = _b64decode(link[8:])
        d = json.loads(raw)
        p = {
            "proxy_type": "vmess",
            "name": d.get("ps", "") or f"VMess-{d.get('add','')}:{d.get('port','')}",
            "host": d.get("add", ""),
            "port": int(d.get("port", 0)),
            "uuid": d.get("id", ""),
            "cipher": d.get("scy", "auto") or "auto",
            "raw_link": link,
        }
        extra = {}
        for k, v in [("aid","alterId"),("net","network"),("path","ws-path"),
                      ("host","host"),("tls","tls"),("sni","sni"),
                      ("fp","fingerprint"),("type","type")]:
            if d.get(k):
                extra[v] = d[k]
        if extra:
            p["extra"] = extra
        return p if p["host"] and p["port"] else None
    except Exception:
        return None


def parse_trojan(link: str) -> Optional[dict]:
    """trojan://password@host:port?params#name"""
    try:
        rest = link[9:]
        if "@" not in rest:
            return None
        password, rest2 = rest.split("@", 1)
        name = ""
        if "#" in rest2:
            rest2, name = rest2.split("#", 1)
        query = {}
        if "?" in rest2:
            rest2, qs = rest2.split("?", 1)
            for kv in qs.split("&"):
                if "=" in kv:
                    k, v = kv.split("=", 1)
                    query[k] = v
        host, port_s = rest2.rsplit(":", 1)
        port = int(port_s)
        p = {
            "proxy_type": "trojan",
            "name": name or f"Trojan-{host}:{port}",
            "host": host, "port": port,
            "password": password,
            "raw_link": link,
        }
        extra = {k: query[k] for k in ("allowInsecure","sni","peer","security","type","flow") if k in query}
        if extra:
            p["extra"] = extra
        return p
    except Exception:
        return None


def parse_vless(link: str) -> Optional[dict]:
    """vless://uuid@host:port?params#name"""
    try:
        rest = link[8:]
        if "@" not in rest:
            return None
        uuid, rest2 = rest.split("@", 1)
        name, query = "", {}
        if "#" in rest2:
            rest2, name = rest2.split("#", 1)
        if "?" in rest2:
            rest2, qs = rest2.split("?", 1)
            for kv in qs.split("&"):
                if "=" in kv:
                    k, v = kv.split("=", 1)
                    query[k] = v
        host, port_s = rest2.rsplit(":", 1)
        port = int(port_s)
        p = {
            "proxy_type": "vless",
            "name": name or f"VLESS-{host}:{port}",
            "host": host, "port": port,
            "uuid": uuid,
            "raw_link": link,
        }
        if query:
            p["extra"] = query
        return p
    except Exception:
        return None


def parse_hysteria2(link: str) -> Optional[dict]:
    """hysteria2:// 或 hy2://"""
    try:
        rest = link[6:] if link.startswith("hy2://") else link[12:]
        if "@" not in rest:
            return None
        password, rest2 = rest.split("@", 1)
        name, query = "", {}
        if "#" in rest2:
            rest2, name = rest2.split("#", 1)
        if "?" in rest2:
            rest2, qs = rest2.split("?", 1)
            for kv in qs.split("&"):
                if "=" in kv:
                    k, v = kv.split("=", 1)
                    query[k] = v
        host, port_s = rest2.rsplit(":", 1)
        port = int(port_s)
        p = {
            "proxy_type": "hysteria2",
            "name": name or f"Hy2-{host}:{port}",
            "host": host, "port": port,
            "password": password,
            "raw_link": link,
        }
        if query:
            p["extra"] = query
        return p
    except Exception:
        return None


_PARSERS = {
    "ss://": parse_ss,
    "vmess://": parse_vmess,
    "trojan://": parse_trojan,
    "vless://": parse_vless,
    "hysteria2://": parse_hysteria2,
    "hy2://": parse_hysteria2,
}


def parse_single_link(line: str) -> Optional[dict]:
    for prefix, parser in _PARSERS.items():
        if line.startswith(prefix):
            return parser(line)
    return None


# ── 整体内容解析 ──────────────────────────────────────────

def parse_plain_text(text: str) -> List[dict]:
    """每行一个链接的纯文本格式。"""
    proxies = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        p = parse_single_link(line)
        if p:
            proxies.append(p)
    return proxies


def parse_clash_yaml(text: str) -> List[dict]:
    """Clash YAML 格式。"""
    try:
        data = yaml.safe_load(text)
    except Exception:
        return []
    if not isinstance(data, dict):
        return []
    raw = data.get("proxies") or data.get("Proxy") or []
    if isinstance(raw, str):
        return []
    proxies = []
    for p in raw if isinstance(raw, list) else []:
        ptype = p.get("type", "")
        proxy = {
            "proxy_type": ptype,
            "name": p.get("name", ""),
            "host": p.get("server", ""),
            "port": p.get("port", 0),
        }
        if ptype == "ss":
            proxy["cipher"] = p.get("cipher", "")
            proxy["password"] = p.get("password", "")
            proxy["plugin"] = p.get("plugin", "")
            proxy["plugin_opts"] = p.get("plugin-opts", "")
        elif ptype == "vmess":
            proxy["uuid"] = p.get("uuid", "")
            proxy["cipher"] = p.get("cipher", "auto")
            extra = {}
            for k in ("alterId","network","ws-path","ws-headers","tls","skip-cert-verify","servername"):
                if p.get(k):
                    extra[k] = p[k]
            if extra:
                proxy["extra"] = extra
        elif ptype == "trojan":
            proxy["password"] = p.get("password", "")
            extra = {k: p[k] for k in ("sni","skip-cert-verify","udp","network") if p.get(k)}
            if extra:
                proxy["extra"] = extra
        elif ptype in ("http","https","socks5"):
            proxy["username"] = p.get("username", "")
            proxy["password"] = p.get("password", "")
        if proxy["host"] and proxy["port"]:
            proxies.append(proxy)
    return proxies


def parse_sip008(data: list) -> List[dict]:
    """SIP008 JSON 格式 [{server, server_port, method, password, ...}]"""
    proxies = []
    for item in data:
        if "server" in item and "server_port" in item:
            proxies.append({
                "proxy_type": "ss",
                "name": item.get("remarks", "") or f"SS-{item['server']}:{item['server_port']}",
                "host": item["server"],
                "port": int(item["server_port"]),
                "cipher": item.get("method", ""),
                "password": item.get("password", ""),
                "plugin": item.get("plugin", ""),
                "plugin_opts": item.get("plugin_opts", ""),
            })
    return proxies


def parse_content(content: bytes, source_url: str = "") -> List[dict]:
    """智能识别格式并解析。"""
    text = content.decode("utf-8", errors="ignore")
    proxies = []

    # 1) Clash YAML
    is_yaml = any(source_url.lower().endswith(e) for e in (".yaml", ".yml"))
    if is_yaml or text.strip().startswith(("proxies:", "port:", "socks-port:", "mixed-port:")):
        proxies = parse_clash_yaml(text)
        if proxies:
            return proxies

    # 2) 纯 base64（整个文件是 base64）
    stripped = text.strip()
    if len(stripped) > 80 and re.match(r"^[A-Za-z0-9+/=\s]+$", stripped):
        try:
            decoded = _b64decode(stripped)
            proxies = parse_plain_text(decoded)
            if proxies:
                return proxies
        except Exception:
            pass

    # 3) JSON (SIP008)
    if stripped.startswith("[") or stripped.startswith("{"):
        try:
            data = json.loads(stripped)
            if isinstance(data, list):
                proxies = parse_sip008(data)
                if proxies:
                    return proxies
        except Exception:
            pass

    # 4) 逐行解析
    proxies = parse_plain_text(text)
    if proxies:
        return proxies

    # 5) 最后试 YAML
    proxies = parse_clash_yaml(text)
    return proxies


async def fetch_and_parse(url: str) -> List[dict]:
    """下载并解析一个订阅源。"""
    try:
        async with aiohttp.ClientSession() as sess:
            async with sess.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status != 200:
                    return []
                content = await resp.read()
                return parse_content(content, url)
    except Exception:
        return []

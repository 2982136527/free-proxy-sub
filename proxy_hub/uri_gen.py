"""通用代理 URI 生成器 — 把内部 proxy dict 转成 ss:///vmess:///trojan:// 等链接。"""
import json
import base64
from typing import Dict
from urllib.parse import quote


def proxy_to_uri(p: dict) -> str | None:
    """将内部代理 dict 转换为 ss:///vmess:///trojan:// 链接。"""
    ptype = p["proxy_type"]
    name = quote(p.get("name", f"{ptype}-{p['host']}"), safe="")

    try:
        if ptype == "ss":
            return _ss_uri(p, name)
        elif ptype == "vmess":
            return _vmess_uri(p, name)
        elif ptype == "trojan":
            return _trojan_uri(p, name)
        elif ptype == "vless":
            return _vless_uri(p, name)
        elif ptype == "hysteria2":
            return _hy2_uri(p, name)
    except Exception:
        return None


def _ss_uri(p: dict, name: str) -> str:
    cipher = p.get("cipher", "aes-256-gcm")
    password = p.get("password", "")
    host = p["host"]
    port = p["port"]
    userinfo = base64.b64encode(f"{cipher}:{password}".encode()).decode()
    return f"ss://{userinfo}@{host}:{port}#{name}"


def _vmess_uri(p: dict, name: str) -> str:
    extra = p.get("extra", {})
    if isinstance(extra, str):
        try:
            extra = json.loads(extra)
        except Exception:
            extra = {}
    obj = {
        "v": "2",
        "ps": name,
        "add": p["host"],
        "port": str(p["port"]),
        "id": p.get("uuid", ""),
        "aid": extra.get("alterId", "0"),
        "scy": p.get("cipher", "auto"),
        "net": extra.get("network", "tcp"),
        "type": extra.get("type", "none"),
        "host": extra.get("host", extra.get("servername", "")),
        "path": extra.get("ws-path", extra.get("path", "")),
        "tls": extra.get("tls", ""),
        "sni": extra.get("sni", ""),
        "fp": extra.get("fingerprint", ""),
        "alpn": extra.get("alpn", ""),
    }
    # Remove empty fields
    obj = {k: v for k, v in obj.items() if v}
    raw = json.dumps(obj, ensure_ascii=False)
    return f"vmess://{base64.b64encode(raw.encode()).decode()}"


def _trojan_uri(p: dict, name: str) -> str:
    password = p.get("password", "")
    host = p["host"]
    port = p["port"]
    extra = p.get("extra", {})
    if isinstance(extra, str):
        try:
            extra = json.loads(extra)
        except Exception:
            extra = {}
    params = ""
    if extra:
        parts = []
        if extra.get("sni"):
            parts.append(f"sni={extra['sni']}")
        if extra.get("peer"):
            parts.append(f"peer={extra['peer']}")
        if extra.get("allowInsecure") in ("1", "true", True):
            parts.append("allowInsecure=1")
        if extra.get("security"):
            parts.append(f"security={extra['security']}")
        if parts:
            params = "?" + "&".join(parts)
    return f"trojan://{quote(password, safe='')}@{host}:{port}{params}#{name}"


def _vless_uri(p: dict, name: str) -> str:
    uuid = p.get("uuid", "")
    host = p["host"]
    port = p["port"]
    extra = p.get("extra", {})
    if isinstance(extra, str):
        try:
            extra = json.loads(extra)
        except Exception:
            extra = {}
    params = "&".join(f"{k}={v}" for k, v in (extra or {}).items())
    if params:
        params = "?" + params
    return f"vless://{uuid}@{host}:{port}{params}#{name}"


def _hy2_uri(p: dict, name: str) -> str:
    password = p.get("password", "")
    host = p["host"]
    port = p["port"]
    extra = p.get("extra", {})
    if isinstance(extra, str):
        try:
            extra = json.loads(extra)
        except Exception:
            extra = {}
    params = "&".join(f"{k}={v}" for k, v in (extra or {}).items())
    if params:
        params = "?" + params
    return f"hysteria2://{quote(password, safe='')}@{host}:{port}{params}#{name}"


def generate_uris(proxies: list) -> list:
    """将多个代理转为 URI 列表，跳过失败的。"""
    uris = []
    for p in proxies:
        uri = proxy_to_uri(p)
        if uri:
            uris.append(uri)
    return uris


def generate_base64_subscription(proxies: list) -> str:
    """生成 Base64 编码的通用订阅内容（Shadowrocket/v2rayN 格式）。"""
    uris = generate_uris(proxies)
    if not uris:
        return ""
    raw = "\n".join(uris)
    return base64.b64encode(raw.encode()).decode()

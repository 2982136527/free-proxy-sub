"""订阅文件生成器 — 输出 Clash 格式 YAML。"""
from typing import List, Dict
import yaml

from .storage import Storage


def _proxy_to_clash(p: dict) -> dict:
    """将内部代理字典转为 Clash YAML proxy 条目。"""
    base = {
        "name": p["name"] or f"{p['proxy_type']}-{p['host']}:{p['port']}",
        "type": p["proxy_type"],
        "server": p["host"],
        "port": p["port"],
    }
    ptype = p["proxy_type"]

    if ptype == "ss":
        base["cipher"] = p.get("cipher", "aes-256-gcm")
        base["password"] = p.get("password", "")
        if p.get("plugin"):
            base["plugin"] = p["plugin"]
            base["plugin-opts"] = p.get("plugin_opts", "")
    elif ptype == "vmess":
        base["uuid"] = p.get("uuid", "")
        base["cipher"] = p.get("cipher", "auto")
        if p.get("extra"):
            extra = p["extra"]
            if isinstance(extra, str):
                import json
                extra = json.loads(extra)
            if isinstance(extra, dict):
                for k, v in extra.items():
                    base[k] = v
        # alterId 默认 0
        base.setdefault("alterId", 0)
    elif ptype == "trojan":
        base["password"] = p.get("password", "")
        if p.get("extra"):
            extra = p["extra"]
            if isinstance(extra, str):
                import json
                extra = json.loads(extra)
            if isinstance(extra, dict):
                base["sni"] = extra.get("sni") or extra.get("peername", "")
                if extra.get("skip-cert-verify"):
                    base["skip-cert-verify"] = True
                if extra.get("udp"):
                    base["udp"] = True
    elif ptype in ("http", "https"):
        base["username"] = p.get("username", "")
        base["password"] = p.get("password", "")
    elif ptype == "hysteria2":
        base["password"] = p.get("password", "")
        if p.get("extra"):
            extra = p["extra"]
            if isinstance(extra, str):
                import json
                extra = json.loads(extra)
            if isinstance(extra, dict):
                for k, v in extra.items():
                    base[k] = v

    return base


def _safe_name(raw: str) -> str:
    """清理 name 中 Clash 不友好的字符。"""
    return raw.replace(" ", "_").replace("\t", "_").replace("\n", "").replace("\r", "")


def generate_clash_yaml(config: dict, storage: Storage) -> str:
    """从存活代理生成 Clash YAML 订阅内容。"""
    scfg = config.get("subscription", {})
    max_proxies = scfg.get("max_proxies", 200)
    hub_name = scfg.get("name", "FreeProxyHub")

    proxies = storage.get_alive_proxies(limit=max_proxies)
    clash_proxies = []
    for p in proxies:
        p["name"] = _safe_name(p.get("name", "") or f"{p['proxy_type']}-{p['host']}:{p['port']}")
        try:
            cp = _proxy_to_clash(p)
            if cp["server"] and cp["port"]:
                clash_proxies.append(cp)
        except Exception:
            continue

    if not clash_proxies:
        # 空订阅
        return yaml.safe_dump({"proxies": []}, default_flow_style=False, allow_unicode=True)

    names_set = set()
    deduped = []
    for cp in clash_proxies:
        n = cp["name"]
        if n in names_set:
            idx = 2
            while f"{n}_{idx}" in names_set:
                idx += 1
            cp["name"] = f"{n}_{idx}"
        names_set.add(cp["name"])
        deduped.append(cp)
    clash_proxies = deduped

    proxy_names = [cp["name"] for cp in clash_proxies]

    # 构建 Clash 配置结构
    result = {
        "port": 7890,
        "socks-port": 7891,
        "allow-lan": False,
        "mode": "Rule",
        "log-level": "warning",
        "ipv6": False,
        "external-controller": "127.0.0.1:9090",
        "proxies": clash_proxies,
        "proxy-groups": [
            {
                "name": "🚀 节点选择",
                "type": "select",
                "proxies": ["🔰 自动选择", "♻️ 自动测速"] + proxy_names,
            },
            {
                "name": "🔰 自动选择",
                "type": "url-test",
                "proxies": proxy_names[:50],
                "url": "https://www.gstatic.com/generate_204",
                "interval": 300,
            },
            {
                "name": "♻️ 自动测速",
                "type": "fallback",
                "proxies": proxy_names[:50],
                "url": "https://www.gstatic.com/generate_204",
                "interval": 300,
            },
        ],
        "rules": [
            "DOMAIN-SUFFIX,google.com,🚀 节点选择",
            "DOMAIN-SUFFIX,youtube.com,🚀 节点选择",
            "DOMAIN-SUFFIX,github.com,🚀 节点选择",
            "DOMAIN-SUFFIX,telegram.org,🚀 节点选择",
            "DOMAIN-SUFFIX,twitter.com,🚀 节点选择",
            "DOMAIN-SUFFIX,x.com,🚀 节点选择",
            "DOMAIN-SUFFIX,instagram.com,🚀 节点选择",
            "DOMAIN-SUFFIX,facebook.com,🚀 节点选择",
            "DOMAIN-SUFFIX,tiktok.com,🚀 节点选择",
            "DOMAIN-SUFFIX,netflix.com,🚀 节点选择",
            "DOMAIN-SUFFIX,disney.com,🚀 节点选择",
            "DOMAIN-SUFFIX,spotify.com,🚀 节点选择",
            "DOMAIN-SUFFIX,steampowered.com,🚀 节点选择",
            "DOMAIN-SUFFIX,openai.com,🚀 节点选择",
            "DOMAIN-SUFFIX,claude.ai,🚀 节点选择",
            "GEOSITE,CN,DIRECT",
            "GEOIP,CN,DIRECT",
            "MATCH,🚀 节点选择",
        ],
    }

    return yaml.safe_dump(result, default_flow_style=False, allow_unicode=True)


def generate_json(config: dict, storage: Storage) -> dict:
    """生成 JSON 格式的节点列表（用于调试/API）。"""
    scfg = config.get("subscription", {})
    max_proxies = scfg.get("max_proxies", 200)
    proxies = storage.get_alive_proxies(limit=max_proxies)
    return {
        "updated": None,
        "count": len(proxies),
        "proxies": [
            {"name": p["name"], "type": p["proxy_type"],
             "server": p["host"], "port": p["port"],
             "latency_ms": p.get("latency_ms")}
            for p in proxies
        ],
    }

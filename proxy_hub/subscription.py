"""订阅文件生成器 — 输出 Clash 格式 YAML。"""
from typing import List, Dict
import urllib.parse
from collections import OrderedDict
import yaml

from .storage import Storage

_COUNTRY_HINTS = OrderedDict({
    "美国": ("🇺🇸", "US"), "us.": ("🇺🇸", "US"), "united states": ("🇺🇸", "US"),
    "日本": ("🇯🇵", "JP"), "jp.": ("🇯🇵", "JP"), "japan": ("🇯🇵", "JP"),
    "韩国": ("🇰🇷", "KR"), "kr.": ("🇰🇷", "KR"), "korea": ("🇰🇷", "KR"),
    "新加坡": ("🇸🇬", "SG"), "sg.": ("🇸🇬", "SG"), "singapore": ("🇸🇬", "SG"),
    "香港": ("🇭🇰", "HK"), "hk.": ("🇭🇰", "HK"),
    "台湾": ("🇹🇼", "TW"), "tw.": ("🇹🇼", "TW"), "taiwan": ("🇹🇼", "TW"),
    "俄罗斯": ("🇷🇺", "RU"), "ru.": ("🇷🇺", "RU"), "russia": ("🇷🇺", "RU"),
    "瑞典": ("🇸🇪", "SE"), "se.": ("🇸🇪", "SE"), "sweden": ("🇸🇪", "SE"),
    "芬兰": ("🇫🇮", "FI"), "fi.": ("🇫🇮", "FI"), "finland": ("🇫🇮", "FI"),
    "英国": ("🇬🇧", "GB"), "uk.": ("🇬🇧", "GB"), "united kingdom": ("🇬🇧", "GB"),
    "德国": ("🇩🇪", "DE"), "de.": ("🇩🇪", "DE"), "germany": ("🇩🇪", "DE"),
    "法国": ("🇫🇷", "FR"), "fr.": ("🇫🇷", "FR"), "france": ("🇫🇷", "FR"),
    "加拿大": ("🇨🇦", "CA"), "ca.": ("🇨🇦", "CA"), "canada": ("🇨🇦", "CA"),
    "澳大利亚": ("🇦🇺", "AU"), "au.": ("🇦🇺", "AU"), "australia": ("🇦🇺", "AU"),
    "印度": ("🇮🇳", "IN"), "in.": ("🇮🇳", "IN"), "india": ("🇮🇳", "IN"),
    "荷兰": ("🇳🇱", "NL"), "nl.": ("🇳🇱", "NL"), "netherlands": ("🇳🇱", "NL"),
    "挪威": ("🇳🇴", "NO"), "no.": ("🇳🇴", "NO"), "norway": ("🇳🇴", "NO"),
    "丹麦": ("🇩🇰", "DK"), "dk.": ("🇩🇰", "DK"), "denmark": ("🇩🇰", "DK"),
    "波兰": ("🇵🇱", "PL"), "pl.": ("🇵🇱", "PL"), "poland": ("🇵🇱", "PL"),
    "西班牙": ("🇪🇸", "ES"), "es.": ("🇪🇸", "ES"), "spain": ("🇪🇸", "ES"),
    "意大利": ("🇮🇹", "IT"), "it.": ("🇮🇹", "IT"), "italy": ("🇮🇹", "IT"),
    "越南": ("🇻🇳", "VN"), "vn.": ("🇻🇳", "VN"), "vietnam": ("🇻🇳", "VN"),
    "马来西亚": ("🇲🇾", "MY"), "my.": ("🇲🇾", "MY"),
    "泰国": ("🇹🇭", "TH"), "th.": ("🇹🇭", "TH"), "thailand": ("🇹🇭", "TH"),
    "土耳其": ("🇹🇷", "TR"), "tr.": ("🇹🇷", "TR"), "turkey": ("🇹🇷", "TR"),
    "瑞士": ("🇨🇭", "CH"), "switzerland": ("🇨🇭", "CH"),
    "爱尔兰": ("🇮🇪", "IE"), "ie.": ("🇮🇪", "IE"), "ireland": ("🇮🇪", "IE"),
    "新西兰": ("🇳🇿", "NZ"), "nz.": ("🇳🇿", "NZ"), "new zealand": ("🇳🇿", "NZ"),
    "南非": ("🇿🇦", "ZA"), "za.": ("🇿🇦", "ZA"), "south africa": ("🇿🇦", "ZA"),
    "巴西": ("🇧🇷", "BR"), "br.": ("🇧🇷", "BR"), "brazil": ("🇧🇷", "BR"),
})


import urllib.parse

def _detect_country(name: str) -> tuple:
    """检测代理名称中的国家信息，返回 (emoji, code)。"""
    try:
        name = urllib.parse.unquote(name)
    except Exception:
        pass
    name_lower = name.lower()
    for keyword, (emoji, code) in _COUNTRY_HINTS.items():
        if keyword in name_lower:
            return emoji, code
    return "", ""


def _clean_selected_name(orig: str, counter: dict) -> str:
    """清理命名，按国家分组计数。"""
    emoji, code = _detect_country(orig)
    if code:
        counter[code] = counter.get(code, 0) + 1
        return f"{emoji} {code}-{counter[code]:02d}"
    # 检测失败：用协议类型
    ptype = orig.split("-")[0] if "-" in orig else orig[:6]
    counter["ZZ"] = counter.get("ZZ", 0) + 1
    return f"🌍 Node-{counter['ZZ']:02d}"


def _proxy_to_clash(p: dict) -> dict:
    """将内部代理字典转为 Clash YAML proxy 条目。"""
    base = {
        "name": p["name"],
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
        base["alterId"] = 0
        if p.get("extra"):
            extra = p["extra"]
            if isinstance(extra, str):
                import json; extra = json.loads(extra)
            for k in ("network", "ws-path", "ws-headers", "tls",
                      "skip-cert-verify", "servername", "host"):
                if extra.get(k):
                    base[k] = extra.get(k)
    elif ptype == "trojan":
        base["password"] = p.get("password", "")
        if p.get("extra"):
            extra = p["extra"]
            if isinstance(extra, str):
                import json; extra = json.loads(extra)
            if extra.get("sni"):
                base["sni"] = extra["sni"]
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
                import json; extra = json.loads(extra)
            for k, v in extra.items():
                base[k] = v
    elif ptype == "vless":
        base["uuid"] = p.get("uuid", "") or ""
        base["cipher"] = "auto"
        base["alterId"] = 0
        if p.get("extra"):
            extra = p["extra"]
            if isinstance(extra, str):
                import json; extra = json.loads(extra)
            # VLESS URI 的 "type" 参数对应 Clash 的 "network" 字段
            net_type = extra.pop("type", None)
            if net_type and not extra.get("network"):
                extra["network"] = net_type
            for k in ("network", "ws-path", "ws-headers", "tls",
                      "skip-cert-verify", "servername", "host",
                      "flow", "encryption", "sni", "fp"):
                if extra.get(k):
                    base[k] = extra.get(k)
        if p.get("extra"):
            extra = p["extra"]
            if isinstance(extra, str):
                import json; extra = json.loads(extra)
            for k, v in extra.items():
                base[k] = v

    return base


# ── 完整订阅 ────────────────────────────────────────

def generate_clash_yaml(config: dict, storage: Storage) -> str:
    """从存活代理生成完整 Clash YAML 订阅。"""
    scfg = config.get("subscription", {})
    max_proxies = scfg.get("max_proxies", 200)
    hub_name = scfg.get("name", "FreeProxyHub")

    proxies = storage.get_alive_proxies(limit=max_proxies)
    clash_proxies = _build_clash_proxies(proxies)
    if not clash_proxies:
        return yaml.safe_dump({"proxies": []}, default_flow_style=False, allow_unicode=True)

    proxy_names = [cp["name"] for cp in clash_proxies]
    top50 = proxy_names[:50]

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
            {"name": "🚀 节点选择", "type": "select",
             "proxies": ["🔰 自动选择", "♻️ 自动测速"] + proxy_names},
            {"name": "🔰 自动选择", "type": "url-test",
             "proxies": top50, "url": "https://www.gstatic.com/generate_204", "interval": 300},
            {"name": "♻️ 自动测速", "type": "fallback",
             "proxies": top50, "url": "https://www.gstatic.com/generate_204", "interval": 300},
        ],
        "rules": [
            "DOMAIN-SUFFIX,google.com,🚀 节点选择",
            "DOMAIN-SUFFIX,youtube.com,🚀 节点选择",
            "DOMAIN-SUFFIX,github.com,🚀 节点选择",
            "DOMAIN-SUFFIX,telegram.org,🚀 节点选择",
            "DOMAIN-SUFFIX,twitter.com,🚀 节点选择",
            "DOMAIN-SUFFIX,instagram.com,🚀 节点选择",
            "DOMAIN-SUFFIX,netflix.com,🚀 节点选择",
            "DOMAIN-SUFFIX,openai.com,🚀 节点选择",
            "DOMAIN-SUFFIX,claude.ai,🚀 节点选择",
            "GEOSITE,CN,DIRECT",
            "GEOIP,CN,DIRECT",
            "MATCH,🚀 节点选择",
        ],
    }
    return yaml.safe_dump(result, default_flow_style=False, allow_unicode=True)


# ── 精选订阅 (top N by latency) ─────────────────────

def generate_clash_selected(config: dict, storage: Storage) -> str:
    """生成精选节点订阅（延迟最低的 N 个）。"""
    scfg = config.get("subscription", {})
    count = scfg.get("selected_count", 30)

    raw = storage.get_alive_proxies(limit=count * 2)  # 多取一些以便筛选
    if not raw:
        return yaml.safe_dump({"proxies": []}, default_flow_style=False, allow_unicode=True)

    # 按延迟排序
    raw.sort(key=lambda p: (p.get("latency_ms") or 9999))
    top = raw[:count]

    # 重新赋予 clean name
    counter = {}
    for p in top:
        orig = p.get("name", "") or f"{p['proxy_type']}-{p['host']}"
        p["name"] = _clean_selected_name(orig, counter)

    clash_proxies = _build_clash_proxies(top)
    proxy_names = [cp["name"] for cp in clash_proxies]

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
            {"name": "🇺🇳 精选节点", "type": "select",
             "proxies": ["♻️ 自动选择"] + proxy_names},
            {"name": "♻️ 自动选择", "type": "url-test",
             "proxies": proxy_names,
             "url": "https://www.gstatic.com/generate_204",
             "interval": 180},
        ],
        "rules": ["MATCH,🇺🇳 精选节点"],
    }
    return yaml.safe_dump(result, default_flow_style=False, allow_unicode=True)


# ── JSON ────────────────────────────────────────────

def generate_json(config: dict, storage: Storage) -> dict:
    scfg = config.get("subscription", {})
    max_proxies = scfg.get("max_proxies", 200)
    proxies = storage.get_alive_proxies(limit=max_proxies)
    return {
        "count": len(proxies),
        "proxies": [
            {"name": p["name"], "type": p["proxy_type"],
             "server": p["host"], "port": p["port"],
             "latency_ms": p.get("latency_ms")}
            for p in proxies
        ],
    }


# ── 内部辅助 ────────────────────────────────────────

def _build_clash_proxies(proxies: List[Dict]) -> List[Dict]:
    """构建 Clash 格式代理列表，去重重名。"""
    result = []
    seen = set()
    for p in proxies:
        name = p.get("name", "") or f"{p['proxy_type']}-{p['host']}"
        # 去重
        if name in seen:
            idx = 2
            while f"{name}_{idx}" in seen:
                idx += 1
            name = f"{name}_{idx}"
        seen.add(name)
        p["name"] = name
        try:
            cp = _proxy_to_clash(p)
            if cp.get("server") and cp.get("port"):
                result.append(cp)
        except Exception:
            continue
    return result

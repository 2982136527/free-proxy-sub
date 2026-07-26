"""订阅文件生成器 — 输出 Clash (mihomo) 格式 YAML。

只输出 mihomo 实际支持的字段；无法在 mihomo 里工作的节点
（未知加密、未知传输层、缺关键参数）直接跳过，避免整包不可用。
"""
import base64
import json
import re
import urllib.parse
from collections import OrderedDict
from typing import List, Dict, Optional

import yaml

from .storage import Storage
from .parser import normalize_extra

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

_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")

# mihomo 支持的 ss 加密方法
_SS_CIPHERS = {
    "aes-128-gcm", "aes-192-gcm", "aes-256-gcm",
    "aes-128-cfb", "aes-192-cfb", "aes-256-cfb",
    "aes-128-ctr", "aes-192-ctr", "aes-256-ctr",
    "rc4-md5", "chacha20-ietf", "xchacha20",
    "chacha20-ietf-poly1305", "xchacha20-ietf-poly1305",
    "2022-blake3-aes-128-gcm", "2022-blake3-aes-256-gcm",
    "2022-blake3-chacha20-poly1305",
}
_VMESS_CIPHERS = {"auto", "none", "zero", "aes-128-gcm", "chacha20-poly1305"}
_CLIENT_FPS = {"chrome", "firefox", "safari", "ios", "android", "edge", "360", "qq", "random"}
_SUPPORTED_NETWORKS = {"tcp", "ws", "grpc", "h2", "http"}


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
    counter["ZZ"] = counter.get("ZZ", 0) + 1
    return f"🌍 Node-{counter['ZZ']:02d}"


def _clean_name(name: str, fallback: str) -> str:
    """URL 解码 + 去控制字符 + 压缩空白 + 截断。"""
    name = str(name or "")
    try:
        name = urllib.parse.unquote(name)
    except Exception:
        pass
    name = re.sub(r"[\x00-\x1f\x7f]", "", name)
    name = re.sub(r"\s+", " ", name).strip()
    if len(name) > 48:
        name = name[:48].rstrip()
    return name or fallback


def _client_fp(extra: dict, *, required: bool = False) -> Optional[str]:
    fp = str(extra.get("fp", "") or "").lower()
    if fp == "randomized":
        fp = "random"
    if fp in _CLIENT_FPS:
        return fp
    return "chrome" if required else None


def _alpn_list(extra: dict) -> Optional[list]:
    alpn = extra.get("alpn")
    if not alpn:
        return None
    if isinstance(alpn, str):
        alpn = [a.strip() for a in alpn.split(",") if a.strip()]
    return alpn or None


def _apply_transport(base: dict, extra: dict) -> bool:
    """写入传输层字段。返回 False 表示该传输层 mihomo 不支持。"""
    net = extra.get("network", "tcp") or "tcp"
    if extra.get("header_type") == "http":
        base["network"] = "http"
        opts = {"method": "GET", "path": [extra.get("http_path") or "/"]}
        if extra.get("http_host"):
            opts["headers"] = {"Host": [str(extra["http_host"])]}
        base["http-opts"] = opts
        return True
    if net not in _SUPPORTED_NETWORKS:
        return False
    if net == "ws":
        base["network"] = "ws"
        opts = {"path": extra.get("ws_path") or "/"}
        if extra.get("ws_host"):
            opts["headers"] = {"Host": str(extra["ws_host"])}
        if extra.get("http_upgrade"):
            opts["v2ray-http-upgrade"] = True
        base["ws-opts"] = opts
    elif net == "grpc":
        base["network"] = "grpc"
        if extra.get("grpc_service_name"):
            base["grpc-opts"] = {"grpc-service-name": str(extra["grpc_service_name"])}
    elif net == "h2":
        base["network"] = "h2"
        opts = {"path": extra.get("h2_path") or "/"}
        if extra.get("h2_host"):
            opts["host"] = [str(extra["h2_host"])]
        base["h2-opts"] = opts
    return True


def _valid_reality(pbk: str, sid: str) -> bool:
    """校验 REALITY 参数：畸形值会让 mihomo 拒绝整个配置文件。"""
    try:
        s = pbk.replace("+", "-").replace("/", "_")
        raw = base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))
    except Exception:
        return False
    if len(raw) != 32:
        return False
    if sid and (len(sid) > 16 or not re.fullmatch(r"[0-9a-fA-F]+", sid)):
        return False
    return True


def _apply_tls(base: dict, extra: dict, *, sni_field: str = "servername") -> bool:
    """写入 TLS / REALITY 字段。返回 False 表示节点不可用（如 reality 缺 pbk）。"""
    if extra.get("tls"):
        base["tls"] = True
        sni = extra.get("sni") or extra.get("ws_host") or extra.get("h2_host") or ""
        if sni:
            base[sni_field] = str(sni)
        if extra.get("skip_cert_verify"):
            base["skip-cert-verify"] = True
        alpn = _alpn_list(extra)
        if alpn:
            base["alpn"] = alpn
        if extra.get("security") == "reality":
            pbk = str(extra.get("reality_pbk", "") or "")
            sid = str(extra.get("reality_sid", "") or "")
            if not pbk or not _valid_reality(pbk, sid):
                return False
            ro = {"public-key": pbk}
            if sid:
                ro["short-id"] = sid
            base["reality-opts"] = ro
            base["client-fingerprint"] = _client_fp(extra, required=True)
        else:
            fp = _client_fp(extra)
            if fp:
                base["client-fingerprint"] = fp
    elif extra.get("security") == "reality":
        return False
    return True


def _proxy_to_clash(p: dict) -> Optional[dict]:
    """将内部代理字典转为 mihomo proxy 条目；不支持的节点返回 None。"""
    ptype = p.get("proxy_type", "")
    host = str(p.get("host", "") or "").strip()
    try:
        port = int(p.get("port", 0) or 0)
    except (TypeError, ValueError):
        return None
    if not host or not (0 < port < 65536):
        return None

    extra = normalize_extra(p)
    if extra.get("security") not in (None, "", "tls", "reality"):
        return None  # 未知 security（如实验性协议）

    base = {
        "name": p.get("name", "") or f"{ptype}-{host}:{port}",
        "type": ptype,
        "server": host,
        "port": port,
    }
    if extra.get("udp"):
        base["udp"] = True

    if ptype == "ss":
        cipher = str(p.get("cipher", "") or "").lower()
        password = str(p.get("password", "") or "")
        if cipher not in _SS_CIPHERS or not password:
            return None
        base["cipher"] = cipher
        base["password"] = password
        plugin = str(p.get("plugin", "") or "")
        if plugin:
            popts = _ss_plugin_opts(plugin, p.get("plugin_opts") or "")
            if popts is None:
                return None  # 无法表达的 plugin，节点必然不可用
            base["plugin"], base["plugin-opts"] = popts

    elif ptype == "vmess":
        uuid = str(p.get("uuid", "") or "").strip()
        if not _UUID_RE.match(uuid):
            return None
        base["uuid"] = uuid
        cipher = str(p.get("cipher", "") or "auto").lower()
        base["cipher"] = cipher if cipher in _VMESS_CIPHERS else "auto"
        base["alterId"] = int(extra.get("alter_id", 0) or 0)
        if not _apply_transport(base, extra):
            return None
        if not _apply_tls(base, extra):
            return None
        if base.get("network") == "h2" and not base.get("tls"):
            return None  # h2 必须走 TLS

    elif ptype == "vless":
        uuid = str(p.get("uuid", "") or "").strip()
        if not _UUID_RE.match(uuid):
            return None
        if extra.get("encryption") not in (None, "", "none"):
            return None  # Xray VLESS Encryption，mihomo/多数客户端不支持
        flow = str(extra.get("flow", "") or "")
        if flow and flow != "xtls-rprx-vision":
            return None
        base["uuid"] = uuid
        if flow:
            if not extra.get("tls") or extra.get("network", "tcp") not in ("tcp", ""):
                return None  # vision 只能走 tcp+tls
            base["flow"] = flow
        if not _apply_transport(base, extra):
            return None
        if not _apply_tls(base, extra):
            return None
        if base.get("network") == "h2" and not base.get("tls"):
            return None

    elif ptype == "trojan":
        password = str(p.get("password", "") or "")
        if not password:
            return None
        base["password"] = password
        if extra.get("network", "tcp") not in ("tcp", "ws", "grpc") \
                or extra.get("header_type") == "http":
            return None  # mihomo 的 trojan 只支持 tcp/ws/grpc，且无 http 伪装
        if not _apply_transport(base, extra):
            return None
        # trojan 永远 TLS；mihomo 用 sni 字段
        extra["tls"] = True
        if not _apply_tls(base, extra, sni_field="sni"):
            return None
        base.pop("tls", None)  # trojan 不需要显式 tls 键

    elif ptype == "hysteria2":
        password = str(p.get("password", "") or "")
        base["password"] = password
        obfs = str(extra.get("obfs", "") or "")
        if obfs:
            if obfs != "salamander":
                return None
            base["obfs"] = obfs
            if extra.get("obfs_password"):
                base["obfs-password"] = str(extra["obfs_password"])
        if extra.get("sni"):
            base["sni"] = str(extra["sni"])
        if extra.get("skip_cert_verify"):
            base["skip-cert-verify"] = True
        alpn = _alpn_list(extra)
        if alpn:
            base["alpn"] = alpn
        ports = str(extra.get("ports", "") or "")
        if ports:
            # 畸形 ports 会让 mihomo 拒绝整个配置，只接受 1000-2000,3000 形式
            ports = ports.replace("/", ",").replace(";", ",")
            if re.fullmatch(r"\d+(?:-\d+)?(?:,\d+(?:-\d+)?)*", ports):
                base["ports"] = ports
        if extra.get("pin_sha256"):
            base["fingerprint"] = str(extra["pin_sha256"])

    elif ptype in ("http", "https"):
        if p.get("username"):
            base["username"] = str(p["username"])
        if p.get("password"):
            base["password"] = str(p["password"])
        base["type"] = "http"
        if ptype == "https":
            base["tls"] = True
    elif ptype == "socks5":
        if p.get("username"):
            base["username"] = str(p["username"])
        if p.get("password"):
            base["password"] = str(p["password"])
    else:
        return None

    return base


def _ss_plugin_opts(plugin: str, opts) -> Optional[tuple]:
    """把 SIP002 plugin 字符串 / clash plugin-opts 转成 mihomo (plugin, plugin-opts)。"""
    plugin = plugin.strip().lower()
    if isinstance(opts, str) and opts.strip().startswith("{"):
        try:
            opts = json.loads(opts)
        except Exception:
            pass
    if isinstance(opts, dict):
        kv = {str(k): v for k, v in opts.items()}
    else:
        kv = {}
        for part in str(opts or "").split(";"):
            if not part:
                continue
            k, sep, v = part.partition("=")
            kv[k.strip()] = v if sep else True

    if plugin in ("obfs", "obfs-local", "simple-obfs"):
        mode = str(kv.get("obfs") or kv.get("mode") or "").lower()
        if mode not in ("http", "tls"):
            return None
        po = {"mode": mode}
        host = kv.get("obfs-host") or kv.get("host")
        if host:
            po["host"] = str(host)
        return "obfs", po
    if plugin == "v2ray-plugin":
        mode = str(kv.get("mode", "websocket")).lower()
        if mode != "websocket":
            return None
        po = {"mode": "websocket"}
        if kv.get("tls") in (True, "true", "1"):
            po["tls"] = True
        if kv.get("host"):
            po["host"] = str(kv["host"])
        if kv.get("path"):
            po["path"] = str(kv["path"])
        return "v2ray-plugin", po
    return None


# ── 完整订阅 ────────────────────────────────────────

_BASE_CONFIG = {
    "port": 7890,
    "socks-port": 7891,
    "allow-lan": False,
    "mode": "Rule",
    "log-level": "warning",
    "ipv6": False,
    "external-controller": "127.0.0.1:9090",
}


def generate_clash_yaml(config: dict, storage: Storage) -> str:
    """从存活代理生成完整 Clash YAML 订阅。"""
    scfg = config.get("subscription", {})
    max_proxies = scfg.get("max_proxies", 200)

    proxies = storage.get_alive_proxies(limit=max_proxies)
    clash_proxies = _build_clash_proxies(proxies)
    if not clash_proxies:
        return yaml.safe_dump({"proxies": []}, default_flow_style=False, allow_unicode=True)

    proxy_names = [cp["name"] for cp in clash_proxies]
    top50 = proxy_names[:50]

    result = dict(_BASE_CONFIG)
    result.update({
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
            "GEOSITE,CN,DIRECT",
            "GEOIP,CN,DIRECT",
            "MATCH,🚀 节点选择",
        ],
    })
    return yaml.safe_dump(result, default_flow_style=False, allow_unicode=True, sort_keys=False)


# ── 精选订阅 (top N by latency) ─────────────────────

def generate_clash_selected(config: dict, storage: Storage) -> str:
    """生成精选节点订阅（延迟最低的 N 个可转换节点）。"""
    scfg = config.get("subscription", {})
    count = scfg.get("selected_count", 30)

    raw = storage.get_alive_proxies(limit=0)  # 已按延迟升序
    counter: dict = {}
    clash_proxies: List[dict] = []
    seen = set()
    for p in raw:
        cp = _proxy_to_clash(p)
        if not cp:
            continue
        orig = _clean_name(p.get("name", ""), f"{p['proxy_type']}-{p['host']}")
        name = _clean_selected_name(orig, counter)
        if name in seen:
            continue
        seen.add(name)
        cp["name"] = name
        clash_proxies.append(cp)
        if len(clash_proxies) >= count:
            break

    if not clash_proxies:
        return yaml.safe_dump({"proxies": []}, default_flow_style=False, allow_unicode=True)

    proxy_names = [cp["name"] for cp in clash_proxies]
    result = dict(_BASE_CONFIG)
    result.update({
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
    })
    return yaml.safe_dump(result, default_flow_style=False, allow_unicode=True, sort_keys=False)


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
    """构建 Clash 格式代理列表：转换 + 清理命名 + 去重。"""
    result = []
    seen = set()
    for p in proxies:
        cp = _proxy_to_clash(p)
        if not cp:
            continue
        name = _clean_name(cp["name"], f"{p['proxy_type']}-{p['host']}:{p['port']}")
        if name in seen:
            idx = 2
            while f"{name} #{idx}" in seen:
                idx += 1
            name = f"{name} #{idx}"
        seen.add(name)
        cp["name"] = name
        result.append(cp)
    return result

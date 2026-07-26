"""通用代理 URI 生成器 — 把内部 proxy dict 转成 ss:///vmess:// 等分享链接。"""
import json
import base64
from urllib.parse import quote

from .parser import normalize_extra


def _fmt_host(host: str) -> str:
    return f"[{host}]" if ":" in host else host


def proxy_to_uri(p: dict) -> str | None:
    """将内部代理 dict 转换为分享链接；无法表达的返回 None。"""
    ptype = p.get("proxy_type", "")
    host = str(p.get("host", "") or "")
    if not host or not p.get("port"):
        return None
    name = quote(str(p.get("name", "") or f"{ptype}-{host}"), safe="")
    extra = normalize_extra(p)

    try:
        if ptype == "ss":
            return _ss_uri(p, extra, name)
        elif ptype == "vmess":
            return _vmess_uri(p, extra, name)
        elif ptype == "trojan":
            return _trojan_uri(p, extra, name)
        elif ptype == "vless":
            return _vless_uri(p, extra, name)
        elif ptype == "hysteria2":
            return _hy2_uri(p, extra, name)
    except Exception:
        return None
    return None


def _ss_uri(p: dict, extra: dict, name: str) -> str | None:
    cipher = str(p.get("cipher", "") or "").lower()
    password = str(p.get("password", "") or "")
    if not cipher or not password:
        return None
    host = _fmt_host(p["host"])
    port = p["port"]
    if cipher.startswith("2022-"):
        # SIP002：2022 系列用明文 userinfo（百分号编码）
        userinfo = f"{quote(cipher, safe='')}:{quote(password, safe='')}"
    else:
        userinfo = base64.urlsafe_b64encode(
            f"{cipher}:{password}".encode()).decode().rstrip("=")
    params = ""
    plugin = str(p.get("plugin", "") or "")
    if plugin:
        opts = p.get("plugin_opts") or ""
        if isinstance(opts, str) and opts.strip().startswith("{"):
            try:
                opts = json.loads(opts)
            except Exception:
                pass
        if isinstance(opts, dict):
            opts = _plugin_opts_str(plugin, opts)
            if opts is None:
                return None
        plugin_full = plugin + (";" + str(opts) if opts else "")
        params = "/?plugin=" + quote(plugin_full, safe="")
    return f"ss://{userinfo}@{host}:{port}{params}#{name}"


def _plugin_opts_str(plugin: str, opts: dict) -> str | None:
    """clash plugin-opts dict → SIP002 plugin 参数串。"""
    plugin = plugin.lower()
    if plugin in ("obfs", "obfs-local", "simple-obfs"):
        mode = str(opts.get("mode", "") or "")
        if not mode:
            return None
        s = f"obfs={mode}"
        if opts.get("host"):
            s += f";obfs-host={opts['host']}"
        return s
    if plugin == "v2ray-plugin":
        parts = []
        if opts.get("tls"):
            parts.append("tls")
        parts.append(f"mode={opts.get('mode', 'websocket')}")
        if opts.get("host"):
            parts.append(f"host={opts['host']}")
        if opts.get("path"):
            parts.append(f"path={opts['path']}")
        return ";".join(parts)
    return None


def _vmess_uri(p: dict, extra: dict, name: str) -> str | None:
    net = extra.get("network", "tcp") or "tcp"
    obj = {
        "v": "2",
        "ps": str(p.get("name", "") or ""),
        "add": p["host"],
        "port": str(p["port"]),
        "id": p.get("uuid", ""),
        "aid": str(extra.get("alter_id", 0) or 0),
        "scy": p.get("cipher", "auto") or "auto",
        "net": net,
        "type": "none",
    }
    if extra.get("header_type") == "http":
        obj["net"] = "tcp"
        obj["type"] = "http"
        if extra.get("http_path"):
            obj["path"] = extra["http_path"]
        if extra.get("http_host"):
            obj["host"] = extra["http_host"]
    elif net == "ws":
        obj["path"] = extra.get("ws_path", "/")
        if extra.get("ws_host"):
            obj["host"] = extra["ws_host"]
    elif net == "grpc":
        if extra.get("grpc_service_name"):
            obj["path"] = extra["grpc_service_name"]
    elif net == "h2":
        obj["net"] = "h2"
        if extra.get("h2_path"):
            obj["path"] = extra["h2_path"]
        if extra.get("h2_host"):
            obj["host"] = extra["h2_host"]
    if extra.get("tls"):
        obj["tls"] = "tls"
        if extra.get("sni"):
            obj["sni"] = extra["sni"]
        if extra.get("fp"):
            obj["fp"] = extra["fp"]
        if extra.get("alpn"):
            obj["alpn"] = extra["alpn"]
    raw = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    return f"vmess://{base64.b64encode(raw.encode()).decode()}"


def _transport_params(extra: dict) -> list:
    """xray 风格 query 参数（vless/trojan 共用传输层部分）。"""
    parts = []
    net = extra.get("network", "tcp") or "tcp"
    if extra.get("header_type") == "http":
        parts.append("type=tcp")
        parts.append("headerType=http")
        if extra.get("http_path"):
            parts.append("path=" + quote(str(extra['http_path']), safe=""))
        if extra.get("http_host"):
            parts.append("host=" + quote(str(extra['http_host']), safe=""))
        return parts
    parts.append(f"type={'httpupgrade' if extra.get('http_upgrade') else net}")
    if net == "ws":
        parts.append("path=" + quote(str(extra.get("ws_path", "/")), safe=""))
        if extra.get("ws_host"):
            parts.append("host=" + quote(str(extra['ws_host']), safe=""))
    elif net == "grpc":
        if extra.get("grpc_service_name"):
            parts.append("serviceName=" + quote(str(extra['grpc_service_name']), safe=""))
    elif net == "h2":
        if extra.get("h2_path"):
            parts.append("path=" + quote(str(extra['h2_path']), safe=""))
        if extra.get("h2_host"):
            parts.append("host=" + quote(str(extra['h2_host']), safe=""))
    return parts


def _tls_params(extra: dict, *, default_tls: bool = False) -> list:
    parts = []
    if extra.get("security") == "reality":
        parts.append("security=reality")
        if extra.get("reality_pbk"):
            parts.append("pbk=" + quote(str(extra['reality_pbk']), safe=""))
        if extra.get("reality_sid"):
            parts.append("sid=" + quote(str(extra['reality_sid']), safe=""))
        if extra.get("reality_spx"):
            parts.append("spx=" + quote(str(extra['reality_spx']), safe=""))
    elif extra.get("tls"):
        if not default_tls:
            parts.append("security=tls")
    elif not default_tls:
        parts.append("security=none")
    if extra.get("tls") or extra.get("security") == "reality":
        if extra.get("sni"):
            parts.append("sni=" + quote(str(extra['sni']), safe=""))
        if extra.get("fp"):
            parts.append("fp=" + quote(str(extra['fp']), safe=""))
        if extra.get("alpn"):
            parts.append("alpn=" + quote(str(extra['alpn']), safe=""))
        if extra.get("skip_cert_verify"):
            parts.append("allowInsecure=1")
    return parts


def _trojan_uri(p: dict, extra: dict, name: str) -> str | None:
    password = str(p.get("password", "") or "")
    if not password:
        return None
    host = _fmt_host(p["host"])
    port = p["port"]
    extra.setdefault("tls", True)
    parts = _tls_params(extra, default_tls=True) + _transport_params(extra)
    params = "?" + "&".join(parts) if parts else ""
    return f"trojan://{quote(password, safe='')}@{host}:{port}{params}#{name}"


def _vless_uri(p: dict, extra: dict, name: str) -> str | None:
    uuid = str(p.get("uuid", "") or "")
    if not uuid or uuid == "None":
        return None
    host = _fmt_host(p["host"])
    port = p["port"]
    enc = extra.get("encryption") or "none"
    parts = ["encryption=" + quote(str(enc), safe="")]
    parts += _tls_params(extra)
    parts += _transport_params(extra)
    if extra.get("flow"):
        parts.append("flow=" + quote(str(extra['flow']), safe=""))
    return f"vless://{uuid}@{host}:{port}?{'&'.join(parts)}#{name}"


def _hy2_uri(p: dict, extra: dict, name: str) -> str | None:
    password = str(p.get("password", "") or "")
    host = _fmt_host(p["host"])
    port = p["port"]
    parts = []
    if extra.get("sni"):
        parts.append("sni=" + quote(str(extra['sni']), safe=""))
    if extra.get("skip_cert_verify"):
        parts.append("insecure=1")
    if extra.get("obfs"):
        parts.append("obfs=" + quote(str(extra['obfs']), safe=""))
        if extra.get("obfs_password"):
            parts.append("obfs-password=" + quote(str(extra['obfs_password']), safe=""))
    if extra.get("alpn"):
        parts.append("alpn=" + quote(str(extra['alpn']), safe=""))
    if extra.get("ports"):
        parts.append("mport=" + quote(str(extra['ports']), safe=""))
    if extra.get("pin_sha256"):
        parts.append("pinSHA256=" + quote(str(extra['pin_sha256']), safe=""))
    params = "?" + "&".join(parts) if parts else ""
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
    raw = "\n".join(uris) + "\n"
    return base64.b64encode(raw.encode()).decode()

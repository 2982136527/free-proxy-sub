"""代理格式解析器 — 支持 Clash YAML / Base64 / SIP008 / 单链接。

内部 proxy dict 的 extra 使用统一的规范键（snake_case）：
  network, tls, sni, fp, alpn, skip_cert_verify, udp,
  ws_path, ws_host, http_upgrade,
  grpc_service_name,
  h2_path, h2_host,
  header_type, http_path, http_host,
  flow, encryption, security,
  reality_pbk, reality_sid, reality_spx,
  alter_id,
  obfs, obfs_password, ports, up, down, pin_sha256
旧数据/旧代码写入的 legacy 键由 normalize_extra() 统一转换。
"""
import json
import base64
import binascii
import re
from typing import List, Optional, Tuple
from urllib.parse import unquote

import yaml
import aiohttp

MAX_FETCH_BYTES = 10 * 1024 * 1024


def _b64decode(s: str) -> str:
    """Base64 解码，兼容 URL-safe 字符与缺失 padding，失败返回空串。"""
    s = "".join(s.split())
    if not s:
        return ""
    s = s.replace("-", "+").replace("_", "/")
    pad = -len(s) % 4
    try:
        return base64.b64decode(s + "=" * pad).decode("utf-8", errors="ignore")
    except (binascii.Error, ValueError):
        return ""


def _split_host_port(hp: str) -> Optional[Tuple[str, int]]:
    """拆分 host:port，支持 [IPv6]:port。"""
    hp = hp.strip()
    if not hp:
        return None
    if hp.startswith("["):
        m = re.match(r"^\[([^\]]+)\]:(\d+)$", hp)
        if not m:
            return None
        host, port_s = m.group(1), m.group(2)
    else:
        if ":" not in hp:
            return None
        host, port_s = hp.rsplit(":", 1)
        if ":" in host:
            # 裸 IPv6 不带括号无法区分端口，拒绝
            return None
    try:
        port = int(port_s)
    except ValueError:
        return None
    host = host.strip()
    if not host or " " in host or not (0 < port < 65536):
        return None
    return host, port


def _parse_query(qs: str) -> dict:
    """解析 query string。不用 parse_qsl：'+' 必须保持字面值（obfs 密码等）。"""
    query = {}
    for kv in qs.split("&"):
        if not kv:
            continue
        k, _, v = kv.partition("=")
        k = k.strip()
        if k:
            query[k] = unquote(v)
    return query


def _parse_uri(link: str, prefix: str):
    """通用 scheme://userinfo@host:port/?query#fragment 解析。

    返回 (userinfo, host, port, query, name) 或 None。
    userinfo 原样返回（可能是 base64，含 '/' 也不会被截断）。
    """
    rest = link[len(prefix):]
    name = ""
    if "#" in rest:
        rest, frag = rest.split("#", 1)
        name = unquote(frag).strip()
    query = {}
    if "?" in rest:
        rest, qs = rest.split("?", 1)
        query = _parse_query(qs)
    if "@" not in rest:
        return None
    userinfo, hostpart = rest.rsplit("@", 1)
    hostpart = hostpart.split("/", 1)[0]
    hp = _split_host_port(hostpart)
    if not hp:
        return None
    host, port = hp
    return userinfo, host, port, query, name


_NET_MAP = {
    "": "tcp", "none": "tcp", "tcp": "tcp", "raw": "tcp",
    "ws": "ws", "websocket": "ws", "httpupgrade": "ws",
    "grpc": "grpc", "gun": "grpc",
    "h2": "h2", "http": "h2",
}


def _extra_from_query(q: dict, *, default_tls: bool = False) -> dict:
    """把 xray 风格分享链接的 query 参数转成规范 extra。"""
    extra = {}

    raw_net = (q.get("type") or q.get("network") or "").lower()
    net = _NET_MAP.get(raw_net, raw_net)  # 未知值原样保留，生成端负责跳过
    extra["network"] = net or "tcp"
    if raw_net == "httpupgrade":
        extra["http_upgrade"] = True

    sec = (q.get("security") or "").lower()
    if sec == "reality":
        extra["tls"] = True
        extra["security"] = "reality"
        if q.get("pbk"):
            extra["reality_pbk"] = q["pbk"]
        if q.get("sid"):
            extra["reality_sid"] = q["sid"]
        if q.get("spx"):
            extra["reality_spx"] = q["spx"]
    elif sec in ("tls", "xtls"):
        extra["tls"] = True
    elif sec in ("", "none"):
        if default_tls:
            extra["tls"] = True
    else:
        extra["security"] = sec  # 未知 security，生成端跳过

    sni = q.get("sni") or q.get("peer") or q.get("servername") or ""
    if sni:
        extra["sni"] = sni
    if q.get("fp"):
        extra["fp"] = q["fp"]
    if q.get("alpn"):
        extra["alpn"] = q["alpn"]
    if (q.get("allowInsecure") or q.get("insecure") or "").lower() in ("1", "true"):
        extra["skip_cert_verify"] = True
    if q.get("flow"):
        extra["flow"] = q["flow"]

    if net == "ws":
        extra["ws_path"] = q.get("path") or "/"
        host_hdr = q.get("host") or ""
        if host_hdr:
            extra["ws_host"] = host_hdr
    elif net == "grpc":
        svc = q.get("serviceName") or q.get("path") or ""
        if svc:
            extra["grpc_service_name"] = svc
        if (q.get("mode") or "").lower() == "multi":
            extra["grpc_multi"] = True
    elif net == "h2":
        if q.get("path"):
            extra["h2_path"] = q["path"]
        if q.get("host"):
            extra["h2_host"] = q["host"]
    elif net == "tcp":
        if (q.get("headerType") or "").lower() == "http":
            extra["header_type"] = "http"
            if q.get("path"):
                extra["http_path"] = q["path"]
            if q.get("host"):
                extra["http_host"] = q["host"]

    return extra


# ── 单链接解析 ─────────────────────────────────────────────

def parse_ss(link: str) -> Optional[dict]:
    """ss:// — SIP002 (含 2022 系列明文 userinfo、plugin 参数) 或 legacy 全 base64。"""
    try:
        parsed = _parse_uri(link, "ss://")
        if parsed:
            userinfo, host, port, query, name = parsed
            raw = _b64decode(userinfo)
            if raw and ":" in raw and "\n" not in raw:
                method, password = raw.split(":", 1)
            else:
                ui = unquote(userinfo)
                if ":" not in ui:
                    return None
                method, password = ui.split(":", 1)
        else:
            # legacy: ss://base64(method:password@host:port)#name
            rest = link[5:]
            name = ""
            if "#" in rest:
                rest, frag = rest.split("#", 1)
                name = unquote(frag).strip()
            # 标准 base64 本身可含 '/'，先整体解码，失败再按路径截断
            raw = _b64decode(rest)
            if not raw or "@" not in raw:
                raw = _b64decode(rest.split("/", 1)[0].split("?", 1)[0])
            if not raw or "@" not in raw:
                return None
            creds, hostpart = raw.rsplit("@", 1)
            if ":" not in creds:
                return None
            method, password = creds.split(":", 1)
            hp = _split_host_port(hostpart)
            if not hp:
                return None
            host, port = hp
            query = {}

        method = method.strip().lower()
        if not method or not password:
            return None
        p = {
            "proxy_type": "ss",
            "name": name or f"SS-{host}:{port}",
            "host": host, "port": port,
            "cipher": method, "password": password,
            "raw_link": link,
        }
        plugin = query.get("plugin", "")
        if plugin:
            head, _, opts = plugin.partition(";")
            p["plugin"] = head.strip()
            p["plugin_opts"] = opts
        return p
    except Exception:
        return None


def parse_vmess(link: str) -> Optional[dict]:
    """vmess://base64(JSON)，兼容 vmess://uuid@host:port?params 变体。"""
    try:
        body = link[8:].split("#", 1)[0]
        raw = _b64decode(body)
        if raw and raw.strip().startswith("{"):
            return _parse_vmess_json(raw, link)
        # 非标准 URL 形式
        parsed = _parse_uri(link, "vmess://")
        if not parsed:
            return None
        uuid, host, port, query, name = parsed
        uuid = unquote(uuid)
        if not uuid:
            return None
        extra = _extra_from_query(query)
        cipher = (query.get("encryption") or "auto").lower() or "auto"
        extra.pop("encryption", None)
        return {
            "proxy_type": "vmess",
            "name": name or f"VMess-{host}:{port}",
            "host": host, "port": port,
            "uuid": uuid, "cipher": cipher,
            "raw_link": link, "extra": extra,
        }
    except Exception:
        return None


def _parse_vmess_json(raw: str, link: str) -> Optional[dict]:
    d = json.loads(raw)
    if not isinstance(d, dict):
        return None
    host = str(d.get("add", "") or "").strip()
    try:
        port = int(float(str(d.get("port", 0) or 0)))
    except ValueError:
        return None
    uuid = str(d.get("id", "") or "").strip()
    if not host or not uuid or not (0 < port < 65536):
        return None

    extra = {}
    try:
        aid = int(str(d.get("aid", 0) or 0))
    except ValueError:
        aid = 0
    if aid:
        extra["alter_id"] = aid

    raw_net = str(d.get("net", "") or "").lower()
    htype = str(d.get("type", "") or "").lower()
    net = _NET_MAP.get(raw_net, raw_net) or "tcp"
    extra["network"] = net
    if raw_net == "httpupgrade":
        extra["http_upgrade"] = True

    path = str(d.get("path", "") or "").strip()
    header_host = str(d.get("host", "") or "").strip()
    if net == "ws":
        extra["ws_path"] = path or "/"
        if header_host:
            extra["ws_host"] = header_host
    elif net == "grpc":
        svc = (str(d.get("serviceName", "") or "") or path).strip()
        if svc:
            extra["grpc_service_name"] = svc.lstrip("/")
    elif net == "h2":
        if path:
            extra["h2_path"] = path
        if header_host:
            extra["h2_host"] = header_host
    elif net == "tcp" and htype == "http":
        extra["header_type"] = "http"
        if path:
            extra["http_path"] = path
        if header_host:
            extra["http_host"] = header_host

    tls_v = str(d.get("tls", "") or "").lower()
    if tls_v in ("tls", "true", "1", "reality"):
        extra["tls"] = True
        sni = str(d.get("sni", "") or "").strip()
        if sni:
            extra["sni"] = sni
        elif header_host:
            extra["sni"] = header_host
    for src, dst in (("fp", "fp"), ("alpn", "alpn")):
        v = str(d.get(src, "") or "").strip()
        if v:
            extra[dst] = v
    if str(d.get("allowInsecure", "") or "").lower() in ("1", "true"):
        extra["skip_cert_verify"] = True

    cipher = str(d.get("scy", "") or d.get("security", "") or "auto").lower() or "auto"
    name = str(d.get("ps", "") or "").strip()
    return {
        "proxy_type": "vmess",
        "name": name or f"VMess-{host}:{port}",
        "host": host, "port": port,
        "uuid": uuid, "cipher": cipher,
        "raw_link": link, "extra": extra,
    }


def parse_trojan(link: str) -> Optional[dict]:
    """trojan://password@host:port?params#name"""
    try:
        parsed = _parse_uri(link, "trojan://")
        if not parsed:
            return None
        password, host, port, query, name = parsed
        password = unquote(password)
        if not password:
            return None
        extra = _extra_from_query(query, default_tls=True)
        return {
            "proxy_type": "trojan",
            "name": name or f"Trojan-{host}:{port}",
            "host": host, "port": port,
            "password": password,
            "raw_link": link, "extra": extra,
        }
    except Exception:
        return None


def parse_vless(link: str) -> Optional[dict]:
    """vless://uuid@host:port?params#name"""
    try:
        parsed = _parse_uri(link, "vless://")
        if not parsed:
            return None
        uuid, host, port, query, name = parsed
        uuid = unquote(uuid).strip()
        if not uuid:
            return None
        extra = _extra_from_query(query)
        enc = (query.get("encryption") or "none").strip()
        if enc.lower() not in ("", "none"):
            # Xray VLESS Encryption（如 mlkem768x25519plus…），多数客户端不支持
            extra["encryption"] = enc
        return {
            "proxy_type": "vless",
            "name": name or f"VLESS-{host}:{port}",
            "host": host, "port": port,
            "uuid": uuid,
            "raw_link": link, "extra": extra,
        }
    except Exception:
        return None


def parse_hysteria2(link: str) -> Optional[dict]:
    """hysteria2:// 或 hy2://，兼容端口跳跃 (host:443-445 / mport 参数) 与无 auth 形式。"""
    try:
        prefix = "hy2://" if link.startswith("hy2://") else "hysteria2://"
        rest = link[len(prefix):]
        name = ""
        if "#" in rest:
            rest, frag = rest.split("#", 1)
            name = unquote(frag).strip()
        query = {}
        if "?" in rest:
            rest, qs = rest.split("?", 1)
            query = _parse_query(qs)
        if "@" in rest:
            password, hostpart = rest.rsplit("@", 1)
            password = unquote(password)
        else:
            password, hostpart = "", rest
        hostpart = hostpart.split("/", 1)[0]

        ports_range = ""
        if ":" not in hostpart.strip("[]"):
            # 官方标准形式允许省略端口，默认 443
            hostpart = f"{hostpart}:443"
        hp = _split_host_port(hostpart)
        if not hp:
            # 端口段可能是 443-445 或 443,8443 的跳跃写法
            m = re.match(r"^(\[[^\]]+\]|[^:\[\]]+):([\d,-]+)$", hostpart)
            if not m:
                return None
            host = m.group(1).strip("[]")
            ports_range = m.group(2)
            first = re.match(r"\d+", ports_range)
            if not first:
                return None
            port = int(first.group(0))
            if not (0 < port < 65536):
                return None
        else:
            host, port = hp

        extra = {}
        sni = query.get("sni") or query.get("peer") or ""
        if sni:
            extra["sni"] = sni
        if (query.get("insecure") or query.get("allowInsecure") or "").lower() in ("1", "true"):
            extra["skip_cert_verify"] = True
        if query.get("obfs"):
            extra["obfs"] = query["obfs"]
        if query.get("obfs-password"):
            extra["obfs_password"] = query["obfs-password"]
        if query.get("alpn"):
            extra["alpn"] = query["alpn"]
        mport = query.get("mport") or query.get("ports") or ports_range
        if mport and mport != str(port):
            extra["ports"] = mport
        if query.get("pinSHA256"):
            extra["pin_sha256"] = query["pinSHA256"]
        for k in ("up", "down"):
            if query.get(k):
                extra[k] = query[k]

        return {
            "proxy_type": "hysteria2",
            "name": name or f"Hy2-{host}:{port}",
            "host": host, "port": port,
            "password": password,
            "raw_link": link, "extra": extra,
        }
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


# ── extra 规范化（兼容旧数据） ─────────────────────────────

_CANONICAL_KEYS = {
    "network", "tls", "sni", "fp", "alpn", "skip_cert_verify", "udp",
    "ws_path", "ws_host", "http_upgrade",
    "grpc_service_name", "grpc_multi",
    "h2_path", "h2_host",
    "header_type", "http_path", "http_host",
    "flow", "encryption", "security",
    "reality_pbk", "reality_sid", "reality_spx",
    "alter_id",
    "obfs", "obfs_password", "ports", "up", "down", "pin_sha256",
}

_TRUE_STRS = ("1", "true", "tls", "yes", "on")


def _truthy(v) -> bool:
    if isinstance(v, str):
        return v.lower() in _TRUE_STRS
    return bool(v)


def normalize_extra(p: dict) -> dict:
    """返回规范化 extra dict。兼容 JSON 字符串与 legacy 键名。"""
    extra = p.get("extra") or {}
    if isinstance(extra, str):
        try:
            extra = json.loads(extra)
        except Exception:
            extra = {}
    if not isinstance(extra, dict):
        extra = {}

    out = {k: v for k, v in extra.items()
           if k in _CANONICAL_KEYS and k != "security" and v not in ("", None)}

    # legacy 键转换（旧版本解析器 / 旧 DB 行）
    if "network" not in out:
        net = extra.get("net") or extra.get("network") or ""
        if not net:
            # 旧行把 xray 分享链接的网络类型存在 'type' 键里
            t = str(extra.get("type", "") or "").lower()
            if t in ("ws", "websocket", "grpc", "gun", "h2", "httpupgrade"):
                net = t
        if not net and (extra.get("ws-path") or extra.get("path")):
            net = "ws"
        net = _NET_MAP.get(str(net).lower(), str(net).lower())
        if net and net != "tcp":
            out["network"] = net
    # security：只保留 reality 与未知值（未知值让生成端跳过节点）；
    # tls/xtls 归一成 tls 布尔；none/'' 丢弃，否则旧的非 TLS 节点会被误杀
    sec = str(extra.get("security", "") or "").lower()
    if _truthy(extra.get("tls")) or sec in ("tls", "xtls", "reality"):
        out["tls"] = True
    if sec == "reality":
        out["security"] = "reality"
        if extra.get("pbk"):
            out.setdefault("reality_pbk", extra["pbk"])
        if extra.get("sid"):
            out.setdefault("reality_sid", extra["sid"])
    elif sec not in ("", "none", "tls", "xtls"):
        out["security"] = sec
    if "header_type" not in out and str(extra.get("headerType", "") or "").lower() == "http":
        out["header_type"] = "http"
        if extra.get("path"):
            out.setdefault("http_path", extra["path"])
        if extra.get("host"):
            out.setdefault("http_host", extra["host"])
    if "sni" not in out:
        sni = extra.get("sni") or extra.get("servername") or extra.get("peer") or ""
        if sni:
            out["sni"] = sni
    if "ws_path" not in out and out.get("network") == "ws":
        path = extra.get("ws-path") or extra.get("path") or "/"
        out["ws_path"] = path
    if "ws_host" not in out and out.get("network") == "ws":
        host_hdr = extra.get("host") or ""
        if isinstance(extra.get("ws-headers"), dict):
            for k, v in extra["ws-headers"].items():
                if str(k).lower() == "host":
                    host_hdr = v
        if host_hdr:
            out["ws_host"] = str(host_hdr)
    if "grpc_service_name" not in out and out.get("network") == "grpc":
        svc = extra.get("serviceName") or extra.get("path") or ""
        if svc:
            out["grpc_service_name"] = str(svc).lstrip("/")
    if _truthy(extra.get("skip-cert-verify")) or _truthy(extra.get("allowInsecure")) or _truthy(extra.get("insecure")):
        out["skip_cert_verify"] = True
    if "fp" not in out:
        fp = extra.get("fingerprint") or extra.get("client-fingerprint") or ""
        if fp:
            out["fp"] = fp
    if "alter_id" not in out:
        aid = extra.get("alterId") or extra.get("aid")
        try:
            aid = int(str(aid))
        except (TypeError, ValueError):
            aid = 0
        if aid:
            out["alter_id"] = aid
    if "flow" not in out and extra.get("flow"):
        out["flow"] = extra["flow"]
    if "encryption" not in out and extra.get("encryption") not in (None, "", "none"):
        out["encryption"] = extra["encryption"]
    if "obfs_password" not in out and extra.get("obfs-password"):
        out["obfs_password"] = extra["obfs-password"]
    if "ports" not in out and (extra.get("mport") or extra.get("ports")):
        out["ports"] = extra.get("mport") or extra.get("ports")
    if _truthy(extra.get("udp")):
        out["udp"] = True

    # tcp 是默认值，省掉
    if out.get("network") == "tcp" and "header_type" not in out:
        out.pop("network", None)
    return out


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


def _pick_ws_host(node: dict) -> str:
    headers = node.get("ws-opts", {}) or {}
    headers = headers.get("headers") or node.get("ws-headers") or {}
    if isinstance(headers, dict):
        for k, v in headers.items():
            if str(k).lower() == "host":
                return str(v)
    return ""


def _clash_common_extra(node: dict) -> dict:
    """从 Clash 节点条目提取传输层/ TLS 规范 extra（现代 + legacy 字段）。"""
    extra = {}
    net = str(node.get("network", "") or "").lower()
    ws_opts = node.get("ws-opts") or {}
    if not net and (ws_opts or node.get("ws-path")):
        net = "ws"
    if net and net != "tcp":
        extra["network"] = net

    if net == "ws":
        path = ""
        if isinstance(ws_opts, dict):
            path = str(ws_opts.get("path", "") or "")
            if ws_opts.get("v2ray-http-upgrade"):
                extra["http_upgrade"] = True
        extra["ws_path"] = path or str(node.get("ws-path", "") or "") or "/"
        host_hdr = _pick_ws_host(node)
        if host_hdr:
            extra["ws_host"] = host_hdr
    elif net == "grpc":
        go = node.get("grpc-opts") or {}
        svc = str(go.get("grpc-service-name", "") or "") if isinstance(go, dict) else ""
        if svc:
            extra["grpc_service_name"] = svc
    elif net in ("h2", "http"):
        ho = node.get("h2-opts") or node.get("http-opts") or {}
        if isinstance(ho, dict):
            path = ho.get("path", "")
            if isinstance(path, list):
                path = path[0] if path else ""
            if path:
                extra["h2_path" if net == "h2" else "http_path"] = str(path)
            hosts = ho.get("host") or (ho.get("headers", {}) or {}).get("Host", "")
            if isinstance(hosts, list):
                hosts = hosts[0] if hosts else ""
            if hosts:
                extra["h2_host" if net == "h2" else "http_host"] = str(hosts)
        if net == "http":
            # Clash 的 network:http 是 tcp+http 伪装
            extra.pop("network", None)
            extra["header_type"] = "http"

    if _truthy(node.get("tls")):
        extra["tls"] = True
    sni = str(node.get("servername", "") or node.get("sni", "") or "")
    if sni:
        extra["sni"] = sni
    if _truthy(node.get("skip-cert-verify")):
        extra["skip_cert_verify"] = True
    fp = str(node.get("client-fingerprint", "") or "")
    if fp:
        extra["fp"] = fp
    alpn = node.get("alpn")
    if isinstance(alpn, list):
        alpn = ",".join(str(a) for a in alpn)
    if alpn:
        extra["alpn"] = str(alpn)
    if _truthy(node.get("udp")):
        extra["udp"] = True
    ro = node.get("reality-opts") or {}
    if isinstance(ro, dict) and ro.get("public-key"):
        extra["tls"] = True
        extra["security"] = "reality"
        extra["reality_pbk"] = str(ro["public-key"])
        if ro.get("short-id") not in (None, ""):
            extra["reality_sid"] = str(ro["short-id"])
    return extra


def parse_clash_yaml(text: str) -> List[dict]:
    """Clash / mihomo YAML 格式（支持现代 ws-opts / reality-opts 等字段）。"""
    try:
        data = yaml.safe_load(text)
    except Exception:
        return []
    if not isinstance(data, dict):
        return []
    raw = data.get("proxies") or data.get("Proxy") or []
    if not isinstance(raw, list):
        return []

    proxies = []
    for node in raw:
        if not isinstance(node, dict):
            continue
        ptype = str(node.get("type", "") or "").lower()
        if ptype == "hy2":
            ptype = "hysteria2"
        host = str(node.get("server", "") or "").strip()
        try:
            port = int(float(str(node.get("port", 0) or 0)))
        except (TypeError, ValueError):
            continue
        if not host or not (0 < port < 65536):
            continue
        proxy = {
            "proxy_type": ptype,
            "name": str(node.get("name", "") or ""),
            "host": host,
            "port": port,
        }

        if ptype == "ss":
            proxy["cipher"] = str(node.get("cipher", "") or "").lower()
            proxy["password"] = str(node.get("password", "") or "")
            if node.get("plugin"):
                proxy["plugin"] = str(node["plugin"])
                opts = node.get("plugin-opts", "")
                proxy["plugin_opts"] = json.dumps(opts) if isinstance(opts, dict) else str(opts or "")
            extra = {}
            if _truthy(node.get("udp")):
                extra["udp"] = True
            if extra:
                proxy["extra"] = extra
        elif ptype == "vmess":
            proxy["uuid"] = str(node.get("uuid", "") or "")
            proxy["cipher"] = str(node.get("cipher", "") or "auto").lower()
            extra = _clash_common_extra(node)
            try:
                aid = int(str(node.get("alterId", 0) or 0))
            except (TypeError, ValueError):
                aid = 0
            if aid:
                extra["alter_id"] = aid
            proxy["extra"] = extra
        elif ptype == "vless":
            proxy["uuid"] = str(node.get("uuid", "") or "")
            extra = _clash_common_extra(node)
            if node.get("flow"):
                extra["flow"] = str(node["flow"])
            if node.get("encryption") not in (None, "", "none"):
                extra["encryption"] = str(node["encryption"])
            proxy["extra"] = extra
        elif ptype == "trojan":
            proxy["password"] = str(node.get("password", "") or "")
            extra = _clash_common_extra(node)
            extra["tls"] = True
            proxy["extra"] = extra
        elif ptype == "hysteria2":
            proxy["password"] = str(node.get("password", "") or node.get("auth", "") or "")
            extra = {}
            for src, dst in (("sni", "sni"), ("obfs", "obfs"),
                             ("obfs-password", "obfs_password"),
                             ("ports", "ports"), ("up", "up"), ("down", "down")):
                if node.get(src) not in (None, ""):
                    extra[dst] = str(node[src])
            if _truthy(node.get("skip-cert-verify")):
                extra["skip_cert_verify"] = True
            alpn = node.get("alpn")
            if isinstance(alpn, list):
                alpn = ",".join(str(a) for a in alpn)
            if alpn:
                extra["alpn"] = str(alpn)
            proxy["extra"] = extra
        elif ptype in ("http", "https", "socks5"):
            proxy["username"] = str(node.get("username", "") or "")
            proxy["password"] = str(node.get("password", "") or "")
        else:
            continue

        if proxy.get("uuid") in ("None",):
            continue
        proxies.append(proxy)
    return proxies


def parse_sip008(data) -> List[dict]:
    """SIP008 JSON：列表或 {version, servers: [...]} 形式。"""
    if isinstance(data, dict):
        data = data.get("servers") or []
    if not isinstance(data, list):
        return []
    proxies = []
    for item in data:
        if not isinstance(item, dict):
            continue
        if "server" in item and "server_port" in item:
            try:
                port = int(item["server_port"])
            except (TypeError, ValueError):
                continue
            if not (0 < port < 65536):
                continue
            proxies.append({
                "proxy_type": "ss",
                "name": item.get("remarks", "") or f"SS-{item['server']}:{port}",
                "host": str(item["server"]),
                "port": port,
                "cipher": str(item.get("method", "") or "").lower(),
                "password": str(item.get("password", "") or ""),
                "plugin": item.get("plugin", "") or "",
                "plugin_opts": item.get("plugin_opts", "") or "",
            })
    return proxies


_B64_BODY_RE = re.compile(r"^[A-Za-z0-9+/=_\-\s]+$")


def parse_content(content: bytes, source_url: str = "") -> List[dict]:
    """智能识别格式并解析。"""
    text = content.decode("utf-8-sig", errors="ignore")  # 剥掉 BOM，避免破坏 base64 嗅探
    stripped = text.strip()
    if not stripped:
        return []

    # 1) Clash YAML
    is_yaml = any(source_url.lower().split("?")[0].endswith(e) for e in (".yaml", ".yml"))
    if is_yaml or stripped.startswith(("proxies:", "port:", "socks-port:", "mixed-port:")) \
            or "\nproxies:" in text:
        proxies = parse_clash_yaml(text)
        if proxies:
            return proxies

    # 2) 纯 base64（整个文件是 base64）
    if len(stripped) > 40 and _B64_BODY_RE.match(stripped):
        decoded = _b64decode(stripped)
        if decoded:
            proxies = parse_plain_text(decoded)
            if proxies:
                return proxies

    # 3) JSON (SIP008)
    if stripped.startswith(("[", "{")):
        try:
            data = json.loads(stripped)
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
    return parse_clash_yaml(text)


_FETCH_HEADERS = {
    # 部分订阅源对默认的 python UA 返回 403
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
}


async def fetch_and_parse(url: str) -> List[dict]:
    """下载并解析一个订阅源。"""
    try:
        async with aiohttp.ClientSession(headers=_FETCH_HEADERS) as sess:
            async with sess.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status != 200:
                    return []
                content = await resp.content.read(MAX_FETCH_BYTES)
                return parse_content(content, url)
    except Exception:
        return []

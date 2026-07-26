"""Configuration loader."""
from pathlib import Path
import yaml

DEFAULT_PATH = Path(__file__).resolve().parent.parent / "config.yaml"


_DEFAULTS = {
    "server": {"host": "0.0.0.0", "port": 8000},
    "github": {
        "token": "",
        "search_queries": [
            "free proxy subscription",
            "shadowsocks config",
            "v2ray config",
            "clash config",
            "ss://",
            "vmess://",
            "trojan://",
            "proxy list",
            "机场 订阅",
        ],
    },
    "crawler": {"interval_minutes": 360},
    "validator": {
        "interval_minutes": 30,
        "concurrency": 100,
        "connect_timeout": 5,
        "max_dead_count": 3,
        "max_batch": 0,
        "recheck_minutes": 30,
        "real_check": True,
        "real_check_max": 3000,
        "real_concurrency": 64,
        "real_timeout_ms": 5000,
        "real_url": "https://www.gstatic.com/generate_204",
    },
    "subscription": {
        "max_proxies": 200,
        "selected_count": 30,
        "name": "FreeProxyHub",
    },
}


def load(path: str | None = None) -> dict:
    path = path or str(DEFAULT_PATH)
    with open(path) as f:
        cfg = yaml.safe_load(f) or {}

    # 逐键合并默认值（浅层 setdefault 会让部分配置丢掉同组其他默认键）
    for section, defaults in _DEFAULTS.items():
        node = cfg.setdefault(section, {})
        if isinstance(node, dict) and isinstance(defaults, dict):
            for k, v in defaults.items():
                node.setdefault(k, v)
    return cfg

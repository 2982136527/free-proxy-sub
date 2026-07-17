"""Configuration loader."""
from pathlib import Path
import yaml

DEFAULT_PATH = Path(__file__).resolve().parent.parent / "config.yaml"


def load(path: str | None = None) -> dict:
    path = path or str(DEFAULT_PATH)
    with open(path) as f:
        cfg = yaml.safe_load(f) or {}

    # defaults
    cfg.setdefault("server", {"host": "0.0.0.0", "port": 8000})
    cfg.setdefault("github", {
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
        ]
    })
    cfg.setdefault("crawler", {"interval_minutes": 30})
    cfg.setdefault("validator", {
        "interval_minutes": 5,
        "concurrency": 50,
        "connect_timeout": 5,
        "max_dead_count": 3,
    })
    cfg.setdefault("subscription", {
        "max_proxies": 200,
        "name": "FreeProxyHub",
    })
    return cfg

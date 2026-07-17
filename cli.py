#!/usr/bin/env python3
"""CLI 入口 — 单次运行：爬取→解析→验证→输出全量+精选订阅文件。"""
import argparse
import base64
import json
import logging
from pathlib import Path

from proxy_hub.config import load as load_config
from proxy_hub.storage import Storage
from proxy_hub.main import run_cycle_sync
from proxy_hub.subscription import generate_clash_yaml, generate_clash_selected, generate_json
from proxy_hub.uri_gen import generate_uris, generate_base64_subscription


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    parser = argparse.ArgumentParser(description="FreeProxyHub CLI")
    parser.add_argument("--config", default=None, help="配置文件路径")
    parser.add_argument("--output-dir", default="dist", help="输出目录 (默认 dist)")
    parser.add_argument("--validate-only", action="store_true",
                        help="仅验证+生成，跳过 GitHub 搜索")
    args = parser.parse_args()

    cfg = load_config(args.config)
    storage = Storage()
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    scfg = cfg.get("subscription", {})
    max_p = scfg.get("max_proxies", 200)
    sel_cnt = scfg.get("selected_count", 30)

    # ── 运行 ──────────────────────────────────────────
    if args.validate_only:
        result = run_cycle_sync(cfg, storage, skip_crawl=True)
    else:
        result = run_cycle_sync(cfg, storage, skip_crawl=False)

    # ── 获取存活节点 ──────────────────────────────────
    all_alive = storage.get_alive_proxies(limit=max_p)

    # ── 1) Clash 全量 ─────────────────────────────────
    yaml_str = generate_clash_yaml(cfg, storage)
    (out_dir / "clash.yaml").write_text(yaml_str, encoding="utf-8")
    print(f"  clash.yaml ({len(yaml_str)} bytes)")

    # ── 2) Clash 精选 ─────────────────────────────────
    yaml_sel = generate_clash_selected(cfg, storage)
    (out_dir / "clash-selected.yaml").write_text(yaml_sel, encoding="utf-8")
    print(f"  clash-selected.yaml ({len(yaml_sel)} bytes)")

    # ── 3) 通用订阅 (Shadowrocket / v2ray / Quantumult) ──
    #    全量 Base64
    b64_all = generate_base64_subscription(all_alive)
    (out_dir / "sub.b64").write_text(b64_all, encoding="utf-8")
    print(f"  sub.b64 ({len(b64_all)} bytes, {len(all_alive)} proxies)")

    #    全量纯文本
    uris_all = generate_uris(all_alive)
    (out_dir / "sub.txt").write_text("\n".join(uris_all), encoding="utf-8")
    print(f"  sub.txt ({sum(len(u) for u in uris_all)} bytes)")

    #    精选 Base64 (延迟最低的 30 个)
    all_by_latency = sorted(all_alive,
                            key=lambda p: (p.get("latency_ms") or 9999))
    sel_alive = all_by_latency[:sel_cnt]
    b64_sel = generate_base64_subscription(sel_alive)
    (out_dir / "sub-selected.b64").write_text(b64_sel, encoding="utf-8")
    print(f"  sub-selected.b64 ({len(b64_sel)} bytes, {len(sel_alive)} proxies)")

    # ── 4) JSON ───────────────────────────────────────
    with open(out_dir / "sub.json", "w") as f:
        json.dump(generate_json(cfg, storage), f, ensure_ascii=False, indent=2)

    # ── 5) 状态 ───────────────────────────────────────
    with open(out_dir / "status.json", "w") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    stats = result.get("stats", {})
    print(f"✅ 完成: 总计 {stats.get('total',0)} 个节点, 存活 {stats.get('alive',0)} 个")

    if stats.get("alive", 0) == 0:
        print("⚠️  没有存活节点，订阅文件为空")


if __name__ == "__main__":
    main()

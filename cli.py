#!/usr/bin/env python3
"""CLI 入口 — 单次运行：爬取→解析→验证→输出全量+精选订阅文件。"""
import argparse
import json
import logging
from pathlib import Path

from proxy_hub.config import load as load_config
from proxy_hub.storage import Storage
from proxy_hub.main import run_cycle_sync
from proxy_hub.subscription import generate_clash_yaml, generate_clash_selected, generate_json


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

    if args.validate_only:
        # 快速模式：种内置源 → 解析 → 验证 → 生成（跳过 GitHub 搜索）
        result = run_cycle_sync(cfg, storage, skip_crawl=True)
    else:
        # 完整模式：GitHub 搜索 → 解析 → 验证 → 生成
        result = run_cycle_sync(cfg, storage, skip_crawl=False)

    # 全量订阅
    yaml_str = generate_clash_yaml(cfg, storage)
    (out_dir / "clash.yaml").write_text(yaml_str, encoding="utf-8")
    print(f"  clash.yaml ({len(yaml_str)} bytes)")

    # 精选订阅（延迟最低的 30 个）
    yaml_sel = generate_clash_selected(cfg, storage)
    (out_dir / "clash-selected.yaml").write_text(yaml_sel, encoding="utf-8")
    print(f"  clash-selected.yaml ({len(yaml_sel)} bytes)")

    # JSON
    with open(out_dir / "sub.json", "w") as f:
        json.dump(generate_json(cfg, storage), f, ensure_ascii=False, indent=2)

    # 状态
    with open(out_dir / "status.json", "w") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    stats = result.get("stats", {})
    print(f"✅ 完成: 总计 {stats.get('total',0)} 个节点, 存活 {stats.get('alive',0)} 个")

    if stats.get("alive", 0) == 0:
        print("⚠️  没有存活节点，订阅文件为空")


if __name__ == "__main__":
    main()

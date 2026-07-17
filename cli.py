#!/usr/bin/env python3
"""CLI 入口 — 单次运行爬取→解析→验证→输出订阅文件。

在 GitHub Actions 中通过此脚本执行完整工作流。
输出文件:
  - dist/clash.yaml       Clash 订阅
  - dist/sub.json         节点列表 JSON
  - dist/status.json      运行状态
"""
import argparse
import json
import logging
import sys
from pathlib import Path

from proxy_hub.config import load as load_config
from proxy_hub.storage import Storage
from proxy_hub.main import run_cycle
from proxy_hub.subscription import generate_clash_yaml, generate_json


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    parser = argparse.ArgumentParser(description="FreeProxyHub CLI")
    parser.add_argument("--config", default=None, help="配置文件路径")
    parser.add_argument("--output-dir", default="dist", help="输出目录 (默认 dist)")
    parser.add_argument("--crawl-only", action="store_true", help="仅爬取")
    parser.add_argument("--validate-only", action="store_true", help="仅验证")

    args = parser.parse_args()

    cfg = load_config(args.config)
    storage = Storage()
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.validate_only:
        from proxy_hub.validator import run_validation_sync
        alive = run_validation_sync(cfg, storage)
        print(f"验证完成: {alive} 个存活")

        yaml_str = generate_clash_yaml(cfg, storage)
        (out_dir / "clash.yaml").write_text(yaml_str, encoding="utf-8")

        with open(out_dir / "sub.json", "w") as f:
            json.dump(generate_json(cfg, storage), f, ensure_ascii=False, indent=2)

        with open(out_dir / "status.json", "w") as f:
            json.dump({"alive": alive, "stats": storage.stats()}, f)
        return

    # 完整周期
    result = run_cycle_sync(cfg, storage)

    # 生成订阅文件
    yaml_str = generate_clash_yaml(cfg, storage)
    (out_dir / "clash.yaml").write_text(yaml_str, encoding="utf-8")

    with open(out_dir / "sub.json", "w") as f:
        json.dump(generate_json(cfg, storage), f, ensure_ascii=False, indent=2)

    with open(out_dir / "status.json", "w") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    stats = result.get("stats", {})
    print(f"✅ 完成: 总计 {stats.get('total',0)} 个节点, "
          f"存活 {stats.get('alive',0)} 个, "
          f"来源 {stats.get('sources',0)} 个")

    # 如果存活节点太少，警告但不报错
    if stats.get("alive", 0) == 0:
        print("⚠️  没有存活节点，订阅文件为空")


def run_cycle_sync(cfg, storage):
    from proxy_hub.main import run_cycle_sync as _run
    return _run(cfg, storage)


if __name__ == "__main__":
    main()

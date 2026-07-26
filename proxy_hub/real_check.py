"""真实可用性验证 — 启动独立 mihomo 实例，经由每个节点发起真实 HTTP 请求。

TCP ping 只能证明端口开放（假节点/挂掉的服务也会通过），这里用 mihomo 的
external-controller /proxies/{name}/delay 接口做协议级验证。

mihomo 来源（按优先级）：
  1. 环境变量 MIHOMO_BIN 指定的二进制
  2. PATH 里的 mihomo
  3. docker (metacubex/mihomo 镜像)
找不到则跳过（返回 None），调用方退回 TCP-only 结果。

安全性：实例只监听 127.0.0.1 的随机空闲端口，不开任何入站代理端口、
不碰系统代理/TUN，与本机已运行的 Clash 互不影响。
"""
import asyncio
import logging
import os
import re
import shutil
import socket
import subprocess
import tempfile
import uuid as uuid_mod
from pathlib import Path
from typing import Dict, List, Optional

import aiohttp
import yaml

from .subscription import _proxy_to_clash

logger = logging.getLogger("real_check")

DEFAULT_TEST_URL = "https://www.gstatic.com/generate_204"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _find_runner() -> Optional[dict]:
    """返回 {'mode': 'bin'|'docker', ...}，找不到 mihomo 返回 None。"""
    bin_path = os.environ.get("MIHOMO_BIN") or shutil.which("mihomo")
    if bin_path and Path(bin_path).exists():
        return {"mode": "bin", "bin": bin_path}
    if shutil.which("docker"):
        try:
            subprocess.run(["docker", "info"], capture_output=True, timeout=10, check=True)
            return {"mode": "docker"}
        except Exception:
            return None
    return None


def _build_config(proxies: List[dict], controller: str) -> Optional[dict]:
    """生成仅含节点与 controller 的最小 mihomo 配置。返回 None 表示无可测节点。

    节点名用 p{id} 保证唯一且 ASCII，避免 URL 编码问题。
    """
    nodes = []
    for p in proxies:
        cp = _proxy_to_clash(p)
        if not cp:
            continue
        cp["name"] = f"p{p['id']}"
        nodes.append(cp)
    if not nodes:
        return None
    return {
        "log-level": "silent",
        "mode": "direct",
        "external-controller": controller,
        "proxies": nodes,
    }


def _tail_log(log_path: Path, container: Optional[str], lines: int = 6) -> str:
    """取 mihomo 的最后几行输出，用于诊断启动失败。"""
    text = ""
    try:
        if container:
            r = subprocess.run(["docker", "logs", "--tail", str(lines), container],
                               capture_output=True, text=True, timeout=15)
            text = r.stdout + r.stderr
        elif log_path.exists():
            text = log_path.read_text(errors="ignore")
    except Exception:
        pass
    return " | ".join(text.strip().splitlines()[-lines:])[:400] or "(无输出)"


async def _wait_controller(base: str, timeout: float = 60.0) -> bool:
    async with aiohttp.ClientSession() as sess:
        deadline = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < deadline:
            try:
                async with sess.get(f"{base}/version",
                                    timeout=aiohttp.ClientTimeout(total=2)) as r:
                    if r.status == 200:
                        return True
            except Exception:
                pass
            await asyncio.sleep(0.5)
    return False


async def _delay_test(base: str, names: List[str], *, url: str,
                      timeout_ms: int, concurrency: int) -> Dict[str, float]:
    """并发调用 delay 接口，返回 {节点名: 延迟ms}（只含成功的）。"""
    results: Dict[str, float] = {}
    sem = asyncio.Semaphore(concurrency)
    conn = aiohttp.TCPConnector(limit=concurrency + 8)
    async with aiohttp.ClientSession(connector=conn) as sess:
        async def one(name: str):
            async with sem:
                try:
                    async with sess.get(
                        f"{base}/proxies/{name}/delay",
                        params={"url": url, "timeout": str(timeout_ms)},
                        timeout=aiohttp.ClientTimeout(total=timeout_ms / 1000 + 10),
                    ) as r:
                        if r.status == 200:
                            data = await r.json()
                            delay = data.get("delay")
                            if isinstance(delay, (int, float)) and delay > 0:
                                results[name] = float(delay)
                except Exception:
                    pass

        await asyncio.gather(*[one(n) for n in names])
    return results


_BAD_PROXY_RE = re.compile(r"proxy (\d+):")


def _config_test(runner: dict, tmpdir: str, cfg_path: Path) -> tuple[bool, str]:
    """跑 mihomo -t 校验配置，返回 (是否通过, 错误文本)。"""
    if runner["mode"] == "bin":
        cmd = [runner["bin"], "-d", tmpdir, "-f", str(cfg_path), "-t"]
    else:
        cmd = ["docker", "run", "--rm", "-v", f"{tmpdir}:/root/.config/mihomo",
               "metacubex/mihomo:latest", "-t"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    except Exception as e:
        return False, str(e)
    return r.returncode == 0, (r.stdout + r.stderr).strip()


def _write_config(conf: dict, cfg_path: Path):
    cfg_path.write_text(yaml.safe_dump(conf, allow_unicode=True), encoding="utf-8")


def _drop_rejected_nodes(runner: dict, conf: dict, tmpdir: str, cfg_path: Path,
                         max_drop: int = 40) -> bool:
    """逐个剔除 mihomo 拒绝的节点，直到整份配置通过。

    单个畸形节点会让 mihomo 拒绝整份配置、进而让真实验证整体失效，
    所以这里必须先把它们摘掉。返回配置最终是否可用。
    """
    for _ in range(max_drop):
        ok, err = _config_test(runner, tmpdir, cfg_path)
        if ok:
            return True
        last = err.splitlines()[-1] if err else ""
        m = _BAD_PROXY_RE.search(last)
        if not m:
            logger.warning("mihomo 配置校验失败且无法定位节点: %s", last[:300])
            return False
        idx = int(m.group(1))
        if not (0 <= idx < len(conf["proxies"])):
            logger.warning("mihomo 报告的节点下标越界: %s", last[:300])
            return False
        bad = conf["proxies"].pop(idx)
        logger.info("剔除 mihomo 拒绝的节点 %s (%s): %s",
                    bad.get("name"), bad.get("type"), last[-120:])
        if not conf["proxies"]:
            return False
        _write_config(conf, cfg_path)
    logger.warning("剔除 %d 个节点后配置仍不可用，跳过真实验证", max_drop)
    return False


async def real_check(proxies: List[dict], config: dict | None = None) -> Optional[Dict[int, float]]:
    """对代理列表做真实连通性验证。

    返回 {proxy_id: delay_ms}（只含可用节点）；环境不具备 mihomo 时返回 None。
    """
    cfg = (config or {}).get("validator", {})
    url = cfg.get("real_url", DEFAULT_TEST_URL)
    timeout_ms = int(cfg.get("real_timeout_ms", 5000))
    concurrency = int(cfg.get("real_concurrency", 64))

    runner = _find_runner()
    if not runner:
        logger.info("未找到 mihomo（二进制或 docker），跳过真实验证")
        return None

    port = _free_port()
    listen = "127.0.0.1" if runner["mode"] == "bin" else "0.0.0.0"
    conf = _build_config(proxies, f"{listen}:{port if runner['mode'] == 'bin' else 9090}")
    if not conf:
        return {}
    tmpdir = tempfile.mkdtemp(prefix="mihomo-check-")
    cfg_path = Path(tmpdir) / "config.yaml"
    _write_config(conf, cfg_path)

    proc = None
    container = None
    log_path = Path(tmpdir) / "mihomo.log"
    try:
        if not _drop_rejected_nodes(runner, conf, tmpdir, cfg_path):
            return None

        if runner["mode"] == "bin":
            with open(log_path, "wb") as logf:
                proc = subprocess.Popen(
                    [runner["bin"], "-d", tmpdir, "-f", str(cfg_path)],
                    stdout=logf, stderr=subprocess.STDOUT)
        else:
            container = f"mihomo-check-{uuid_mod.uuid4().hex[:8]}"
            subprocess.run(
                ["docker", "run", "-d", "--rm", "--name", container,
                 "-p", f"127.0.0.1:{port}:9090",
                 "-v", f"{tmpdir}:/root/.config/mihomo",
                 "metacubex/mihomo:latest"],
                capture_output=True, timeout=60, check=True)

        base = f"http://127.0.0.1:{port}"
        if not await _wait_controller(base):
            logger.warning("mihomo controller 未就绪，跳过真实验证: %s",
                           _tail_log(log_path, container))
            return None

        names = [n["name"] for n in conf["proxies"]]
        logger.info("真实验证 %d 个节点 (并发 %d, 超时 %dms) …",
                    len(names), concurrency, timeout_ms)
        name_delay = await _delay_test(base, names, url=url,
                                       timeout_ms=timeout_ms,
                                       concurrency=concurrency)
        return {int(n[1:]): d for n, d in name_delay.items()}
    except Exception as e:
        logger.warning("真实验证异常: %s", e)
        return None
    finally:
        if proc is not None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
        if container is not None:
            subprocess.run(["docker", "rm", "-f", container],
                           capture_output=True, timeout=30)
        shutil.rmtree(tmpdir, ignore_errors=True)


async def apply_real_check(config: dict, storage) -> Optional[int]:
    """对当前 TCP 存活节点做真实验证并更新库。

    返回真实存活数；mihomo 不可用返回 None（保持 TCP 结果）。
    """
    vcfg = config.get("validator", {})
    if not vcfg.get("real_check", True):
        return None
    max_n = int(vcfg.get("real_check_max", 3000))
    candidates = storage.get_alive_proxies(limit=max_n)
    # hysteria2 不做 TCP 粗筛（UDP 协议），单独并入真实验证
    seen_ids = {p["id"] for p in candidates}
    hy2 = [p for p in storage.get_proxies_by_type("hysteria2", limit=500)
           if p["id"] not in seen_ids]
    candidates = candidates + hy2
    if not candidates:
        return 0

    result = await real_check(candidates, config)
    if result is None:
        return None
    if not result and len(candidates) >= 20:
        # 大候选集全军覆没大概率是测试链路故障（如测试 URL 不可达），
        # 不能据此把整个存活集清零
        logger.warning("真实验证 0/%d 通过，疑似测试链路故障，保留 TCP 结果",
                       len(candidates))
        return None

    # 只对实际送测过的节点下结论；无法转成 clash 的节点（仍可能出现在
    # b64/txt 订阅里）保持 TCP 判定的原状态
    testable = {p["id"] for p in candidates if _proxy_to_clash(p)}
    for p in candidates:
        pid = p["id"]
        if pid in result:
            storage.update_proxy_status(pid, True, result[pid])
        elif pid in testable:
            storage.update_proxy_status(pid, False)
    return len(result)


def apply_real_check_sync(config: dict, storage) -> Optional[int]:
    return asyncio.run(apply_real_check(config, storage))

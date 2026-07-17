# FreeProxyHub

免费代理订阅聚合器。自动从 GitHub 搜索免费代理订阅链接，解析、验证后整合成多种格式的订阅链接。

## 订阅地址

所有订阅文件通过 GitHub Pages 部署，国内部分地区可能访问较慢。下面同时提供 **直链** 和 **镜像加速** 两种地址。

### Clash / Mihomo / Stash

| 类型 | 原始链接 | 镜像加速 |
|------|---------|----------|
| 全量节点 (200) | `https://2982136527.github.io/free-proxy-sub/clash.yaml` | `https://gh-proxy.com/https://raw.githubusercontent.com/2982136527/free-proxy-sub/main/dist/clash.yaml` |
| 精选节点 (30) | `https://2982136527.github.io/free-proxy-sub/clash-selected.yaml` | `https://gh-proxy.com/https://raw.githubusercontent.com/2982136527/free-proxy-sub/main/dist/clash-selected.yaml` |

### Shadowrocket / v2rayN / v2rayNG / Quantumult X

| 类型 | 原始链接 | 镜像加速 |
|------|---------|----------|
| 全量节点 (200) | `https://2982136527.github.io/free-proxy-sub/sub.b64` | `https://gh-proxy.com/https://raw.githubusercontent.com/2982136527/free-proxy-sub/main/dist/sub.b64` |
| 精选节点 (30) | `https://2982136527.github.io/free-proxy-sub/sub-selected.b64` | `https://gh-proxy.com/https://raw.githubusercontent.com/2982136527/free-proxy-sub/main/dist/sub-selected.b64` |

### 纯文本（调试用）### 纯文本（调试用）

| | 地址 |
|------|------|
| **源链接** | `https://2982136527.github.io/free-proxy-sub/sub.txt` |
| **镜像加速** | `https://gh-proxy.com/https://raw.githubusercontent.com/2982136527/free-proxy-sub/main/dist/sub.txt` |

> 镜像使用的是 `gh-proxy.com`。如果失效可尝试 `gh.api.99988866.xyz`、`github.moeyy.xyz` 等同类服务，或将链接中的 `raw.githubusercontent.com` 替换为镜像地址。

### 导入客户端

**Clash / Mihomo**：复制表格中对应原始链接 → 客户端 → 订阅 → 添加

**Shadowrocket (小火箭)**：复制 `全量节点` 或 `精选节点` 的原始链接 → 小火箭 → 添加订阅

**v2rayN / v2rayNG**：复制 `全量节点` 或 `精选节点` 的原始链接 → 订阅设置 → 导入

---

## 工作原理

```
GitHub 搜索 → 发现订阅源 → 解析节点 → TCP 连通性验证 → 生成多格式订阅
     ↑                                                         │
     └────────── 定时循环 ──────────────────────────────────────┘
```

## 工作流定时

| 工作流 | 定时 | 做什么 |
|--------|------|--------|
| `update.yml` (全量更新) | **每 6 小时** | 搜 GitHub → 解析 → TCP 验证 → 清理 → 生成全量+精选 → 提交+部署 |
| `quick-validate.yml` (精选刷新) | **每 1 小时** | 内置源解析 → TCP 快速验证 → 刷新精选节点 → 部署 |

## 快速部署

### 1. Fork 仓库

### 2. 启用 GitHub Pages

仓库 → Settings → Pages → **GitHub Actions**

### 3. 等待首次运行

首次运行会自动触发。也可以手动触发：Actions → **Full Update** → Run workflow

## 本地运行

```bash
pip install -r requirements.txt

# 一次性运行（全量：爬取+验证+生成）
python cli.py

# 快速验证模式（跳过 GitHub 搜索，只验证+刷新）
python cli.py --validate-only

# 本地服务器模式
python run.py
# → http://localhost:8000/clash.yaml
```

## 配置文件

编辑 `config.yaml`：

```yaml
github:
  token: "ghp_xxx"          # GitHub Token，提高 API 频率限制
  search_queries:           # 自定义搜索关键词
    - "free proxy subscription"
    - "v2ray config"

validator:
  concurrency: 50           # 并发 TCP 验证数
  connect_timeout: 5        # 连接超时（秒）
  max_dead_count: 3         # 连续 3 次死亡后删除

subscription:
  max_proxies: 200          # 全量订阅最大节点数
  selected_count: 30        # 精选节点数
```

## 支持的协议

Shadowsocks (ss://) · VMess (vmess://) · Trojan (trojan://) · VLESS (vless://) · Hysteria2 (hy2://)

## 支持的订阅格式

Clash YAML · Base64 (v2rayN/Shadowrocket) · SIP008 JSON · 纯文本每行一个链接

## 项目结构

```
├── .github/workflows/
│   ├── update.yml            # 全量更新（每 6 小时）
│   └── quick-validate.yml    # 精选刷新（每 1 小时）
├── config.yaml
├── cli.py
├── proxy_hub/
│   ├── crawler.py            # GitHub 爬虫
│   ├── parser.py             # 代理格式解析
│   ├── validator.py          # TCP 连通性验证
│   ├── uri_gen.py            # 通用 URI 生成 (ss:///vmess://)
│   ├── subscription.py       # Clash YAML 生成
│   ├── server.py             # FastAPI 本地服务器
│   └── main.py               # 工作流编排
└── dist/                     # 生成的订阅文件
```

## License

MIT

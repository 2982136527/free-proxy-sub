# FreeProxyHub

免费代理订阅聚合器。自动从 GitHub 搜索免费代理订阅链接，解析、验证后整合成多种格式的订阅链接。

## 订阅地址

运行完成后，以下文件会自动部署到 GitHub Pages：

### Clash / Mihomo / Stash

| 类型 | 地址 |
|------|------|
| **全量节点** | `https://2982136527.github.io/free-proxy-sub/clash.yaml` |
| **精选节点** (延迟最低 30 个) | `https://2982136527.github.io/free-proxy-sub/clash-selected.yaml` |

### Shadowrocket (小火箭) / v2rayN / v2rayNG / Quantumult X

| 类型 | 地址 |
|------|------|
| **全量 Base64** | `https://2982136527.github.io/free-proxy-sub/sub.b64` |
| **全量明文** | `https://2982136527.github.io/free-proxy-sub/sub.txt` |
| **精选 Base64** (延迟最低 30 个) | `https://2982136527.github.io/free-proxy-sub/sub-selected.b64` |

> 小火箭导入 `sub.b64` 或 `sub.txt`，v2rayN/v2rayNG 导入 `sub.b64`。

### Raw 直链（无需 Pages）

```
https://raw.githubusercontent.com/2982136527/free-proxy-sub/main/dist/clash.yaml
https://raw.githubusercontent.com/2982136527/free-proxy-sub/main/dist/sub.b64
```

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

# 一次性运行
python cli.py

# 本地服务器模式
python run.py
```

## 配置文件

编辑 `config.yaml`：

```yaml
github:
  token: "ghp_xxx"          # GitHub Token，提高 API 频率限制

validator:
  concurrency: 50
  connect_timeout: 5
  max_dead_count: 3

subscription:
  max_proxies: 200           # 全量订阅最大节点数
  selected_count: 30         # 精选节点数
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

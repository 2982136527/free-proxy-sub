# FreeProxyHub

免费代理订阅聚合器。自动从 GitHub 搜索免费代理订阅链接，解析、验证后整合成 Clash / v2ray 可用的订阅链接。

## 工作原理

```
GitHub 搜索 → 发现订阅源 → 解析节点 → TCP 连通性验证 → 生成 clash.yaml
     ↑                                                         │
     └────────── 定时循环（每 4 小时）──────────────────────────┘
```

## 快速使用（一键部署）

### 1. Fork 这个仓库

### 2. 启用 GitHub Pages

仓库 → Settings → Pages → Source 选 **GitHub Actions**

### 3. 等待首次运行

Workflows 会在 4 小时内自动触发。也可以手动触发：
仓库 → Actions → **Update Proxy Subscription** → Run workflow

### 4. 获取订阅链接

运行完成后，你会得到两种订阅地址：

| 类型 | 地址 |
|------|------|
| GitHub Pages | `https://<你的用户名>.github.io/<仓库名>/clash.yaml` |
| Raw 直链 | `https://raw.githubusercontent.com/<你的用户名>/<仓库名>/gh-pages/clash.yaml` |

> 如果启用 GitHub Actions 自动部署时环境变量 `GITHUB_TOKEN` 被正确设置，订阅链接会自动可用。

### 5. 导入 Clash / Clash Meta

将上述订阅链接填入客户端的 **远程配置 / 订阅** 地址即可。

---

## 本地运行

```bash
# 安装依赖
pip install -r requirements.txt

# 一次性运行（爬取→验证→生成文件到 dist/）
python cli.py

# 本地服务器模式（FastAPI + 后台定时调度）
python run.py
# 访问 http://localhost:8000/clash.yaml
```

## 配置文件

编辑 `config.yaml` 自定义行为：

```yaml
github:
  token: "ghp_xxx"          # GitHub Token，提高 API 频率限制
  search_queries:
    - "free proxy subscription"
    - "shadowsocks config"
    # ...

validator:
  concurrency: 50            # 并发验证数
  connect_timeout: 5         # 连接超时（秒）
  max_dead_count: 3          # 连续 3 次死亡后删除

subscription:
  max_proxies: 200           # 订阅最大节点数
```

## 支持的协议

- Shadowsocks (ss://)
- VMess (vmess://)
- Trojan (trojan://)
- VLESS (vless://)
- Hysteria2 (hysteria2:// / hy2://)

## 支持的订阅格式

- Clash YAML (proxies 字段)
- Base64 编码（v2rayN / Shadowrocket 格式）
- SIP008 JSON
- 纯文本每行一个链接

## 项目结构

```
├── .github/workflows/update.yml   # GitHub Actions 工作流
├── config.yaml                     # 配置文件
├── cli.py                          # CLI 入口（用于 GitHub Actions）
├── run.py                          # 本地运行器
├── proxy_hub/
│   ├── crawler.py                  # GitHub 爬虫
│   ├── parser.py                   # 代理格式解析器
│   ├── validator.py                # TCP 连通性验证
│   ├── storage.py                  # SQLite 存储
│   ├── subscription.py            # 订阅文件生成
│   ├── server.py                   # FastAPI 服务器
│   └── main.py                     # 核心工作流
└── dist/                           # 生成的订阅文件（自动生成）
```

## License

MIT

# AgentScope Docker 运行说明

本目录将仓库中的两个应用分别构建为独立镜像：

- `agentscope-agent-service:local`：FastAPI Agent Service，容器端口 `8000`
- `agentscope-web-ui:local`：Nginx 承载的 Web UI，容器端口 `8080`

Compose 只启动 Agent Service 和 Web UI，不会创建 Redis 容器。Agent Service 使用 `.env` 中配置的现有 Redis 和 S3 对象存储；Agent 工作区仍持久化到宿主机，知识库上传的原始文件存入 S3。

镜像构建会排除 `examples/agent_service/workspaces`，不会把本地会话、技能或 MCP 凭据打入镜像。Compose 通过宿主机目录挂载工作区，Kubernetes 通过 `agentscope-workspaces` PVC 持久化工作区。

## 前置条件

- Docker Desktop 或 Docker Engine 已启动
- Docker Compose v2 可用（执行 `docker compose version` 验证）
- 已有一个可从 Docker 容器访问的 Redis 实例
- 已创建一个可用的 AWS S3 或 S3 兼容 Bucket
- 已取得当前示例所需的 Zilliz Cloud/Milvus Token

以下命令都从仓库根目录执行。

## 一键构建并启动

PowerShell：

```powershell
Copy-Item docker/.env.example docker/.env
notepad docker/.env
docker compose --env-file docker/.env -f docker/compose.yaml up -d --build
```

Bash：

```bash
cp docker/.env.example docker/.env
${EDITOR:-vi} docker/.env
docker compose --env-file docker/.env -f docker/compose.yaml up -d --build
```

必须检查 `.env` 中的 Redis 和 S3 参数，并把 `MILVUS_TOKEN` 改为真实值。Redis 和 S3 Endpoint 必须能从容器网络访问；容器中的 `localhost` 指向容器自身，不能用于访问宿主机服务。Docker Desktop 上的宿主机可填写 `host.docker.internal`。`.env` 已被 Git 忽略，不要将密钥写入 Dockerfile、Compose 或提交到仓库。

AWS S3 使用方式：

- `S3_ENDPOINT` 留空
- `AWS_REGION` 填写 Bucket 所在区域
- 使用 `AWS_ACCESS_KEY_ID` 和 `AWS_SECRET_ACCESS_KEY`，或由运行环境提供 IAM Role 凭据

MinIO、阿里云 OSS、Cloudflare R2 等 S3 兼容服务需要填写完整的 `S3_ENDPOINT`。MinIO 通常使用 `S3_ADDRESSING_STYLE=path`；AWS S3 和大多数云服务可使用默认的 `auto`。Bucket 必须预先创建，并至少授予 `GetObject`、`PutObject`、`DeleteObject` 权限。

启动完成后访问：

- Web UI：<http://localhost:8080>
- Agent Service 健康检查：<http://localhost:8000/health>
- Agent Service API 文档：<http://localhost:8000/docs>

首次打开 Web UI 时，在设置页填写：

- Server URL：`http://localhost:8000`
- Username：任意稳定的用户标识，例如 `local-user`

如果修改了 `.env` 中的端口，请同步替换以上 URL。

## 检查运行状态

```powershell
docker compose --env-file docker/.env -f docker/compose.yaml ps
docker compose --env-file docker/.env -f docker/compose.yaml logs -f agent-service
```

健康检查：

```powershell
Invoke-RestMethod http://localhost:8000/health
Invoke-RestMethod http://localhost:8080/api/health
```

Bash 可使用：

```bash
curl --fail http://localhost:8000/health
curl --fail http://localhost:8080/api/health
```

## 分别构建镜像

无需 Compose 时，可以独立构建两份镜像：

```powershell
docker build -f docker/agent-service.Dockerfile -t agentscope-agent-service:local .
docker build -f docker/web-ui.Dockerfile -t agentscope-web-ui:local .
```

Agent Service 镜像包含 Python 3.11、Node.js 22、Playwright MCP 和系统 Chromium，因此首次构建下载量较大。Chromium 通过 Debian 软件源安装，构建和容器运行时均不再从 `cdn.playwright.dev` 下载浏览器。Playwright MCP 默认固定为 `0.0.78`；需要升级时可传入构建参数：

```powershell
docker build --build-arg PLAYWRIGHT_MCP_VERSION=0.0.78 -f docker/agent-service.Dockerfile -t agentscope-agent-service:local .
```

如果当前网络无法访问 Debian、npm 或官方 PyPI，可同时指定可用镜像：

```powershell
docker build `
  --build-arg DEBIAN_MIRROR=http://mirrors.aliyun.com/debian `
  --build-arg DEBIAN_SECURITY_MIRROR=http://mirrors.aliyun.com/debian-security `
  --build-arg NPM_REGISTRY=https://registry.npmmirror.com `
  --build-arg PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple `
  -f docker/agent-service.Dockerfile `
  -t agentscope-agent-service:local .
```

## 构建、推送并更新 Kubernetes

使用不可变的新标签构建 Agent Service 镜像，避免 Kubernetes 在 `imagePullPolicy: IfNotPresent` 下继续使用节点中缓存的旧镜像：

```powershell
docker build `
  --build-arg DEBIAN_MIRROR=http://mirrors.aliyun.com/debian `
  --build-arg DEBIAN_SECURITY_MIRROR=http://mirrors.aliyun.com/debian-security `
  --build-arg NPM_REGISTRY=https://registry.npmmirror.com `
  --build-arg PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple `
  -f docker/agent-service.Dockerfile `
  -t 172.19.10.7:8888/agent/agentscope-agent-service:skill-tools-20260727 .

docker push 172.19.10.7:8888/agent/agentscope-agent-service:skill-tools-20260727

kubectl -n agentscope set image deployment/agentscope-agent-service `
  agent-service=172.19.10.7:8888/agent/agentscope-agent-service:skill-tools-20260727

kubectl -n agentscope rollout status deployment/agentscope-agent-service
```

同时将 `docker/k8s-deployment.yaml` 中 Agent Service 的 `image` 修改为相同标签，避免后续重新执行 `kubectl apply` 时恢复旧镜像。

部署完成后验证 Skill 安装工具、运行用户、Bash、Chromium 和 Playwright MCP：

```powershell
kubectl -n agentscope exec deployment/agentscope-agent-service -- `
  bash -lc "id -u && curl --version && git --version && jq --version && chromium --version && playwright-mcp --version && cat <(printf shell-ok)"
```

预期 `id -u` 输出 `1000`，最后输出 `shell-ok`。首次构建需要从 Debian 软件源下载 Chromium 及其依赖，耗时取决于镜像源速度；该层成功后会由 Docker 缓存。

## 停止、重启与清理

```powershell
# 停止并删除 Agent Service 和 Web UI 容器
docker compose --env-file docker/.env -f docker/compose.yaml down

# 重新启动
docker compose --env-file docker/.env -f docker/compose.yaml up -d

```

`down` 不会操作外部 Redis、S3 Bucket，也不会删除宿主机上的以下目录：

- `examples/agent_service/workspaces`

## 配置项

| 变量 | 必填 | 默认值 | 用途 |
| --- | --- | --- | --- |
| `MILVUS_TOKEN` | 是 | 无 | 连接当前示例配置的 Zilliz Cloud/Milvus |
| `MILVUS_URI` | 否 | 当前示例的 Zilliz Cloud 地址 | 覆盖 Milvus 服务地址 |
| `MILVUS_DB_NAME` | 否 | `default` | Milvus 数据库名称 |
| `REDIS_HOST` | 是 | 无 | 可从容器访问的现有 Redis 地址 |
| `REDIS_PORT` | 否 | `6379` | 现有 Redis 端口 |
| `REDIS_PASSWORD` | 否 | 空 | 现有 Redis 密码 |
| `REDIS_DB` | 否 | `0` | Redis 逻辑数据库 |
| `S3_BUCKET` | 是 | 无 | 已预先创建的对象存储 Bucket |
| `S3_ENDPOINT` | AWS 否，兼容服务是 | 空 | S3 兼容服务的完整 Endpoint URL |
| `S3_USE_SSL` | 否 | `true` | 是否使用 TLS；生产环境应保持开启 |
| `S3_ADDRESSING_STYLE` | 否 | `auto` | `auto`、`path` 或 `virtual` |
| `S3_SIGNATURE_VERSION` | 否 | `s3v4` | S3 请求签名版本 |
| `AWS_REGION` | 否 | `us-east-1` | Bucket 所在区域 |
| `AWS_ACCESS_KEY_ID` | 否 | 空 | 静态访问密钥；使用 IAM Role 时留空 |
| `AWS_SECRET_ACCESS_KEY` | 否 | 空 | 静态访问密钥；使用 IAM Role 时留空 |
| `AWS_SESSION_TOKEN` | 否 | 空 | STS 临时凭据 Token |
| `AGENT_SERVICE_PORT` | 否 | `8000` | Agent Service 的宿主机端口 |
| `WEB_UI_PORT` | 否 | `8080` | Web UI 的宿主机端口 |
| `AMAP_API_KEY` | 否 | 空 | 启用高德地图 MCP |
| `LUCKIN_MCP_TOKEN` | 否 | 空 | 启用瑞幸 MCP |
| `PLAYWRIGHT_MCP_COMMAND` | 否 | `playwright-mcp` | 使用镜像内预装的 Playwright MCP，避免容器启动时访问 npm |
| `PLAYWRIGHT_MCP_ARGS` | 否 | `--headless --no-sandbox --executable-path /opt/playwright-browser/chrome` | 使用镜像内 Chromium 的容器启动参数 |

Web UI 的 Agent Service 地址由浏览器设置页保存，因此同一镜像可以连接不同环境，不需要重新构建。切换到 S3 后，原来 `examples/agent_service/blobs` 中的文件不会自动上传，Redis 中已有的本地 Blob URI 也不会自动改写；旧知识库文档需要迁移后更新元数据，或在新部署中重新上传并索引。

## 常见问题

查看某个服务的日志：

```powershell
docker compose --env-file docker/.env -f docker/compose.yaml logs --tail=200 agent-service
docker compose --env-file docker/.env -f docker/compose.yaml logs --tail=200 web-ui
```

若 `agent-service` 持续处于 `unhealthy`，优先检查 `MILVUS_TOKEN` 是否有效、容器能否访问配置的 Zilliz Cloud 地址、外部 Redis 地址和凭据，以及 S3 Bucket、Endpoint 和访问凭据是否正确。若端口已被占用，在 `.env` 中修改 `AGENT_SERVICE_PORT` 或 `WEB_UI_PORT` 后重新执行 `up -d`。

若 MCP 面板中没有 `browser-use`，检查日志中是否出现 npm 超时或 `Failed to connect stateful MCP 'browser-use'`。镜像已预装固定版本的 Playwright MCP，正常配置不应使用 `npx @playwright/mcp@latest`：

```powershell
docker exec agentscope-agent-service-1 playwright-mcp --version
docker compose --env-file docker/.env -f docker/compose.yaml restart agent-service
```

服务启动时会自动迁移工作区中旧的 `npx @playwright/mcp@latest` 配置，并把高德、瑞幸 HTTP MCP 改为无状态连接，避免跨请求复用已关闭的会话而触发 `anyio.ClosedResourceError`。

若工具调用提示 `/opt/google/chrome/chrome` 不存在，说明仍在使用未指定浏览器路径的旧配置。当前镜像通过 `/opt/playwright-browser/chrome` 指向构建阶段安装的 Chromium，容器运行时不会再次下载浏览器；重新构建并替换 Agent Service 容器即可应用该配置。

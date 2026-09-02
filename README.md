# CrossCheck AI

多模型答案验证与共识平台。

并行调用多个大模型，提取答案中的关键声明，使用外部工具（搜索 / 代码执行 / 约束检查）自动验证，
输出：推荐答案（含置信度）、共识点与分歧点、每条声明的证据来源与验证状态、各模型原始对比。

> 对应完整 PRD / 系统设计见项目任务书（外部文档）。本仓库由 Anneal 开发。

## 开发环境

- Python >= 3.11（用 uv 管理：`uv venv .venv && uv pip install -e .`）
- 本地服务：`uv run uvicorn crosscheck.main:app --reload --port 8000`
- 健康检查：`GET /health`
- 数据库迁移：部署时运行 `uv run python -m crosscheck.migrate`，按编号执行幂等迁移；应用启动不隐式建表。
- 前端：`cd frontend && npm install && npm run dev`（仅使用 `VITE_API_BASE_URL`，不读取模型密钥）
- 后端焦点测试：`uv run pytest -q tests/test_tracer.py`

## 环境变量

复制 `.env.example` 为 `.env` 并填入密钥（API Key 为运行时外部服务凭据，最后再配）。

`GET /health` 不访问数据库、Redis 或模型服务，因此在缺少可选集成配置时仍保持
`{"status":"ok"}`。查询报告只有在 PostgreSQL 持久化事务成功后才会返回；本地
测试也支持 `sqlite+aiosqlite` URL。

## 可复现全栈

复制 `.env.example` 为 `.env`，只填写准备启用的 provider key，然后执行：

```bash
docker compose build sandbox-image backend frontend
docker compose run --rm migrate
docker compose up --wait postgres redis backend frontend
curl http://localhost:8000/health
```

Python 代码验证使用本地 `crosscheck-python-sandbox:3.11.9` 镜像，运行时禁用网络、只读
文件系统、丢弃 capabilities，并限制非 root 用户、CPU、内存、PID 和超时。回归命令：
`uv run pytest -q` 与 `cd frontend && npm ci && npm test -- --run`。
Linux 主机应把 `DOCKER_GID` 设为 `/var/run/docker.sock` 的组 ID，使非 root 后端仅获得
访问本地沙箱 daemon 所需的组权限。

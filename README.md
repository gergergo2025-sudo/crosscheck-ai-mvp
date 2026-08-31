# CrossCheck AI

多模型答案验证与共识平台。

并行调用多个大模型，提取答案中的关键声明，使用外部工具（搜索 / 代码执行 / 约束检查）自动验证，
输出：推荐答案（含置信度）、共识点与分歧点、每条声明的证据来源与验证状态、各模型原始对比。

> 对应完整 PRD / 系统设计见项目任务书（外部文档）。本仓库由 Anneal 开发。

## 开发环境

- Python >= 3.11（用 uv 管理：`uv venv .venv && uv pip install -e .`）
- 本地服务：`uv run uvicorn crosscheck.main:app --reload --port 8000`
- 健康检查：`GET /health`

## 环境变量

复制 `.env.example` 为 `.env` 并填入密钥（API Key 为运行时外部服务凭据，最后再配）。
"""FastAPI 入口。当前含健康检查与 /api/query 占位；后续由 Anneal 实现完整流水线。"""

from fastapi import FastAPI

app = FastAPI(
    title="CrossCheck AI",
    version="0.1.0",
    description="多模型答案验证与共识平台",
)


@app.get("/health")
async def health() -> dict[str, str]:
    """健康检查。"""
    return {"status": "ok"}


@app.get("/api/query", include_in_schema=False)
async def query_placeholder() -> dict[str, str]:
    """占位：正式能力由 POST /api/query 提供（多模型并行调用 + 声明验证 + 评分）。"""
    return {"status": "not_implemented", "message": "POST /api/query 待实现（Anneal）"}
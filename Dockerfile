FROM ghcr.io/astral-sh/uv:0.8.15-python3.11-bookworm-slim@sha256:a5496800aed99aa347f859d355073138f7a9929ec2049a6e116c1cdf36676533
WORKDIR /app
ENV UV_LINK_MODE=copy PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN apt-get update && apt-get install -y --no-install-recommends docker.io && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
COPY migrations ./migrations
RUN uv sync --frozen --no-dev && adduser --disabled-password --gecos '' --uid 10001 crosscheck && chown -R crosscheck:crosscheck /app
USER 10001
EXPOSE 8000
CMD ["uv", "run", "uvicorn", "crosscheck.main:app", "--host", "0.0.0.0", "--port", "8000"]

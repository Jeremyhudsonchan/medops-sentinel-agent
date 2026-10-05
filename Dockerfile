FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080

RUN pip install --no-cache-dir uv

COPY pyproject.toml README.md agents-cli-manifest.yaml ./
COPY app ./app
COPY eval ./eval
COPY scripts ./scripts

RUN uv pip install --system --no-cache .

EXPOSE 8080

CMD ["adk", "web", "--host", "0.0.0.0", "--port", "8080", "--allow_origins", "*", "--no_use_local_storage", "app"]

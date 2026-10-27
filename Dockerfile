FROM python:3.14-slim

WORKDIR /app
COPY pyproject.toml uv.lock* README.md ./
RUN pip install --no-cache-dir uv && uv sync --frozen --no-dev --no-install-project
COPY src ./src
COPY migrations ./migrations
RUN uv sync --frozen --no-dev

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1
EXPOSE 8080
CMD ["uvicorn", "moretztrichter.main:app", "--host", "0.0.0.0", "--port", "8080"]

# Mirrors render.yaml: install requirements, generate the synthetic batch and run
# the pipeline at build time, then start uvicorn.
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src ./src
COPY scripts ./scripts
COPY frontend ./frontend

RUN python -m scripts.generate_data && python -m scripts.run_pipeline

# Non-root user; the app writes to data/ (SQLite) and results/ (audit log) at runtime.
RUN useradd --create-home --uid 1000 app \
    && mkdir -p data results logs \
    && chown -R app:app /app
USER app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.environ.get('PORT', '8000') + '/healthz', timeout=4)"

CMD uvicorn src.api.server:app --host 0.0.0.0 --port ${PORT:-8000}

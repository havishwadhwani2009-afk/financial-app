FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
COPY pyproject.toml ./
RUN pip install -e ".[dev]" || true
COPY . .
RUN pip install -e .
RUN useradd -m app && chown -R app /app
USER app
EXPOSE 8000
CMD ["sh", "-c", "python -m app.cli migrate && uvicorn app.main:app --host 0.0.0.0 --port 8000"]

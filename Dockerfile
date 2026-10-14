FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 RAGDESK_INDEX=/data/index.pkl RAGDESK_DOCS=/docs
WORKDIR /app
COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /usr/local/bin/uv
COPY pyproject.toml README.md LICENSE ./
COPY ragdesk ./ragdesk
RUN uv pip install --system --no-cache ".[slack]"
# sample docs; mount your own at /docs
COPY samples/handbook /docs
VOLUME /data
EXPOSE 8000
CMD ["uvicorn", "ragdesk.api:app", "--host", "0.0.0.0", "--port", "8000"]

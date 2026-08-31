FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md ./
COPY qnode_auditor ./qnode_auditor
RUN pip install --no-cache-dir .
USER 65532:65532
EXPOSE 8000
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "2", "--threads", "4", "--timeout", "30", "qnode_auditor.app:app"]

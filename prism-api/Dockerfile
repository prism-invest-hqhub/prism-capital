FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .
COPY prism_api.py .
COPY static/ ./static/

EXPOSE 8900

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -f http://localhost:8900/health || exit 1

CMD ["python3", "-m", "uvicorn", "prism_api:app", "--host", "0.0.0.0", "--port", "8900"]

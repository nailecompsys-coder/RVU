FROM python:3.11-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends libpq-dev gcc curl && rm -rf /var/lib/apt/lists/*
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/app ./app
COPY frontend/dist /app/frontend/dist
ENV PYTHONPATH=/app
ENV RVU_STATIC_DIST=/app/frontend/dist
EXPOSE 3010
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "3010", "--workers", "2"]

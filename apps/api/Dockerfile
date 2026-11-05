FROM python:3.12-slim-bookworm AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 && rm -rf /var/lib/apt/lists/*
COPY requirements.lock.txt /app/requirements.lock.txt
RUN pip install --no-cache-dir -r requirements.lock.txt
COPY apps/api /app/apps/api
COPY ml /app/ml
COPY scripts /app/scripts
COPY docs /app/docs
RUN useradd --uid 10001 --create-home fastlane && mkdir -p /app/data/raw /app/data/backups /app/data/operations /app/tmp && chown -R fastlane:fastlane /app/data /app/tmp
USER fastlane
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "apps.api.main:app", "--host", "0.0.0.0", "--port", "8000"]

FROM runtime AS hosted
COPY deploy/bundle/models/ /app/ml/artifacts/
COPY deploy/bundle/history.json /app/data/processed/kaggle-2018-2025/history.json

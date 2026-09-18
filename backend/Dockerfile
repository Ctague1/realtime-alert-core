FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY backend/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY backend/app /app/app
COPY database/migrations/init.sql /app/database/migrations/init.sql
# The sensor generator, used by the optional "sensor" Compose service
# (docker compose --profile sensor up).
COPY scripts/stream.py /app/scripts/stream.py

EXPOSE 8000

# The same image runs both the API/ingestion process and the processing
# worker; docker-compose overrides the command for the worker service.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
# Dockerfile
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies
# libpq-dev is needed for asyncpg/psycopg2 PostgreSQL drivers
RUN apt-get update && apt-get install -y \
    libpq-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first (Docker layer caching)
# This means if only your code changes, pip install is skipped
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of your application
COPY . .

# Cloud Run injects PORT environment variable at runtime
# FastAPI/Uvicorn must listen on this port — NOT hardcoded 8000
ENV PORT=8080

# Run the application
# host 0.0.0.0 is required — localhost would reject Cloud Run's health checks
CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT}
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies for psycopg2 and compilation
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python requirements
COPY apps/fastapi-api/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy FastAPI application files
COPY apps/fastapi-api ./

# Expose FastAPI port
EXPOSE 8000

ENV FASTAPI_PORT=8000

CMD ["python", "main.py"]

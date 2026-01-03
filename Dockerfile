FROM python:3.11-slim

# Install system dependencies including ffmpeg
RUN apt-get update && apt-get install -y \
    ffmpeg \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY . /app
WORKDIR /app

ENV REDIS_URL=${REDIS_URL:-redis://localhost:6379}
ENV UPLOAD_SECRET_KEY=${UPLOAD_SECRET_KEY:-yoursecretkeyhere}

EXPOSE 8000
CMD ["gunicorn", "--bind", "0.0.0.0:$PORT", "--workers", "2", "--timeout", "120", "--log-level", "info", "app:app"]
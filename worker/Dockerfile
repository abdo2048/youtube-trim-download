FROM python:3.11-slim

# Install system dependencies including ffmpeg
RUN apt-get update && apt-get install -y \
    ffmpeg \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY . /worker
WORKDIR /worker

ENV REDIS_URL=${REDIS_URL:-redis://redis:6379/0}
ENV UPLOAD_URL=${UPLOAD_URL:-http://localhost:8000/uploadfromworker}
ENV UPLOAD_SECRET_KEY=${UPLOAD_SECRET_KEY:-yoursecretkeyhere}

CMD ["celery", "-A", "worker.tasks", "worker", "--loglevel=info", "--pool=solo"]
FROM python:3.11-slim

RUN apt-get update && apt-get install -y \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

WORKDIR /flower

EXPOSE 5555
CMD ["celery", "-A", "worker.tasks", "flower", "--port=5555", "--broker=redis://redis:6379"]
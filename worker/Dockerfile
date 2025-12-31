FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libnss3 libx11-6 libxkbcommon0 libxcomposite1 libxdamage1 libxrandr2 \
    libgbm1 libasound2 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 \
    libxfixes3 libxshmfence1 libxext6 libxrender1 libx11-xcb1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt \
    && playwright install --with-deps chromium

COPY . /app/worker
ENV PYTHONPATH=/app/worker

CMD ["python", "worker/worker.py"]

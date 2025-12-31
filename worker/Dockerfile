FROM mcr.microsoft.com/playwright/python:v1.57.0-noble

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY . /app/worker

CMD ["python", "/app/worker/worker.py"]

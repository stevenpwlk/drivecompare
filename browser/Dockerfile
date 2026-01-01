FROM mcr.microsoft.com/playwright/python:v1.57.0-noble

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        xvfb \
        x11vnc \
        openbox \
        novnc \
        websockify \
        curl \
        openssl \
    && rm -rf /var/lib/apt/lists/*

RUN python -m playwright install chromium

ENV DISPLAY=:99

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 5801 9222

ENTRYPOINT ["/entrypoint.sh"]

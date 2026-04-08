FROM python:3.12-slim

# Install ffmpeg and system deps
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install yt-dlp from source + API dependencies
COPY . /app
RUN pip install --no-cache-dir -e ".[default]" && \
    pip install --no-cache-dir fastapi uvicorn[standard]

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

CMD ["uvicorn", "api_server:app", "--host", "0.0.0.0", "--port", "8000"]

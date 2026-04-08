FROM python:3.12-slim

# Install ffmpeg, curl, unzip and system deps
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg curl unzip && \
    rm -rf /var/lib/apt/lists/*

# Install deno (required by yt-dlp for YouTube JS extraction)
RUN curl -fsSL https://deno.land/install.sh | DENO_INSTALL=/usr/local sh
ENV DENO_DIR=/tmp/deno

WORKDIR /app

# Install yt-dlp + API dependencies
RUN pip install --no-cache-dir yt-dlp fastapi "uvicorn[standard]" python-multipart

# Copy only the API server
COPY api_server.py /app/api_server.py

# Persistent data directory (cookies + downloads)
RUN mkdir -p /app/data
VOLUME /app/data
ENV COOKIES_FILE=/app/data/cookies.txt
ENV DOWNLOAD_DIR=/tmp/yt-dlp-downloads

EXPOSE 8000

CMD ["uvicorn", "api_server:app", "--host", "0.0.0.0", "--port", "8000"]

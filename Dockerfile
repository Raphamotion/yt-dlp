FROM python:3.12-slim

# Install ffmpeg and system deps
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install yt-dlp + API dependencies
RUN pip install --no-cache-dir yt-dlp fastapi "uvicorn[standard]"

# Copy only the API server
COPY api_server.py /app/api_server.py

EXPOSE 8000

CMD ["uvicorn", "api_server:app", "--host", "0.0.0.0", "--port", "8000"]

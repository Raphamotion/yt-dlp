"""yt-dlp REST API Server — exposes yt-dlp functionality over HTTP."""

import json
import os
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, HttpUrl

app = FastAPI(
    title="yt-dlp API",
    description="REST API wrapper for yt-dlp — download and extract info from videos",
    version="1.0.0",
)

DOWNLOAD_DIR = Path(os.getenv("DOWNLOAD_DIR", "/tmp/yt-dlp-downloads"))
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

COOKIES_FILE = Path(os.getenv("COOKIES_FILE", "/app/cookies.txt"))

MAX_TIMEOUT = int(os.getenv("MAX_TIMEOUT", "300"))


# ── Models ───────────────────────────────────────────────────────────────────

class InfoRequest(BaseModel):
    url: str


class DownloadRequest(BaseModel):
    url: str
    format: str = "best"
    extract_audio: bool = False
    audio_format: str = "mp3"
    output_template: str | None = None
    extra_args: list[str] | None = None


# ── Helpers ──────────────────────────────────────────────────────────────────

def _cookie_args() -> list[str]:
    """Return --cookies flag if cookies file exists."""
    if COOKIES_FILE.is_file() and COOKIES_FILE.stat().st_size > 0:
        return ["--cookies", str(COOKIES_FILE)]
    return []


def _run_ytdlp(args: list[str], timeout: int = MAX_TIMEOUT) -> subprocess.CompletedProcess:
    """Run yt-dlp as a subprocess with timeout."""
    cmd = ["yt-dlp", *_cookie_args(), *args]
    try:
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as e:
        raise HTTPException(status_code=408, detail=f"yt-dlp timed out after {timeout}s") from e


# ── Endpoints ────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    """Health check."""
    result = _run_ytdlp(["--version"], timeout=10)
    has_cookies = COOKIES_FILE.is_file() and COOKIES_FILE.stat().st_size > 0
    return {
        "status": "ok",
        "yt_dlp_version": result.stdout.strip(),
        "cookies_loaded": has_cookies,
    }


@app.post("/cookies")
async def upload_cookies(file: UploadFile = File(...)):
    """Upload a Netscape cookies.txt file for authenticated downloads (YouTube, etc)."""
    content = await file.read()
    if len(content) > 1_000_000:
        raise HTTPException(status_code=400, detail="Cookies file too large (max 1MB)")
    text = content.decode("utf-8", errors="replace")
    if "# Netscape HTTP Cookie File" not in text and "# HTTP Cookie File" not in text:
        raise HTTPException(status_code=400, detail="Invalid cookies.txt format — must be Netscape format")
    COOKIES_FILE.write_bytes(content)
    return {"status": "ok", "message": "Cookies uploaded", "size_bytes": len(content)}


@app.delete("/cookies")
async def delete_cookies():
    """Remove the stored cookies file."""
    if COOKIES_FILE.is_file():
        COOKIES_FILE.unlink()
        return {"status": "deleted"}
    raise HTTPException(status_code=404, detail="No cookies file found")


@app.post("/info")
async def get_info(req: InfoRequest):
    """Get video/playlist metadata without downloading."""
    result = _run_ytdlp(["--dump-json", "--no-download", req.url])
    if result.returncode != 0:
        raise HTTPException(status_code=400, detail=result.stderr.strip())
    # Handle playlists (multiple JSON objects, one per line)
    lines = result.stdout.strip().splitlines()
    if len(lines) == 1:
        return json.loads(lines[0])
    return [json.loads(line) for line in lines if line.strip()]


@app.post("/formats")
async def list_formats(req: InfoRequest):
    """List available formats for a URL."""
    result = _run_ytdlp(["--list-formats", "--no-download", req.url])
    if result.returncode != 0:
        raise HTTPException(status_code=400, detail=result.stderr.strip())
    return {"formats": result.stdout.strip()}


@app.post("/download")
async def download(req: DownloadRequest):
    """Download media and return the file path / metadata."""
    job_id = str(uuid.uuid4())
    job_dir = DOWNLOAD_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    output_tpl = req.output_template or "%(title)s.%(ext)s"
    args = [
        "-f", req.format,
        "-o", str(job_dir / output_tpl),
        "--no-playlist",
        "--restrict-filenames",
    ]

    if req.extract_audio:
        args.extend(["-x", "--audio-format", req.audio_format])

    if req.extra_args:
        # Only allow safe flags — block shell-sensitive patterns
        blocked = {"--exec", "--batch-file", "--config-location", "--cookies"}
        for arg in req.extra_args:
            if any(arg.startswith(b) for b in blocked):
                raise HTTPException(status_code=400, detail=f"Blocked argument: {arg}")
        args.extend(req.extra_args)

    args.append(req.url)

    result = _run_ytdlp(args)
    if result.returncode != 0:
        # Cleanup on failure
        shutil.rmtree(job_dir, ignore_errors=True)
        raise HTTPException(status_code=400, detail=result.stderr.strip())

    # Find downloaded files
    files = list(job_dir.iterdir())
    if not files:
        shutil.rmtree(job_dir, ignore_errors=True)
        raise HTTPException(status_code=500, detail="Download completed but no files found")

    return {
        "job_id": job_id,
        "files": [
            {"name": f.name, "size_bytes": f.stat().st_size}
            for f in files
        ],
    }


@app.get("/download/{job_id}/{filename}")
async def get_file(job_id: str, filename: str):
    """Retrieve a downloaded file by job ID and filename."""
    # Sanitize to prevent path traversal
    safe_job = Path(job_id).name
    safe_file = Path(filename).name
    file_path = DOWNLOAD_DIR / safe_job / safe_file

    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(file_path, filename=safe_file)


@app.delete("/download/{job_id}")
async def cleanup(job_id: str):
    """Delete downloaded files for a job."""
    safe_job = Path(job_id).name
    job_dir = DOWNLOAD_DIR / safe_job
    if job_dir.is_dir():
        shutil.rmtree(job_dir)
        return {"status": "deleted", "job_id": job_id}
    raise HTTPException(status_code=404, detail="Job not found")


@app.get("/version")
async def version():
    """Get yt-dlp version."""
    result = _run_ytdlp(["--version"], timeout=10)
    return {"version": result.stdout.strip()}

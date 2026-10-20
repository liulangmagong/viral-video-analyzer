"""Local-only media ingestion: no network downloads and no model calls."""
import asyncio
import hashlib
import json
import math
from pathlib import Path

from config import settings
from models.schemas import ImportMetadata, VideoMeta


async def probe_media(path: Path) -> dict:
    proc = await asyncio.create_subprocess_exec(
        "ffprobe", "-v", "error", "-protocol_whitelist", "file,pipe",
        "-show_streams", "-show_format", "-of", "json", str(path),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
    except BaseException:
        if proc.returncode is None:
            proc.kill()
        await proc.communicate()
        raise
    if proc.returncode:
        raise ValueError("Invalid or unsupported video")
    info = json.loads(stdout)
    streams = info.get("streams", [])
    duration = float(info.get("format", {}).get("duration", 0))
    if not any(s.get("codec_type") == "video" for s in streams):
        raise ValueError("A video stream is required")
    if not math.isfinite(duration) or not 0 < duration <= settings.MAX_IMPORT_DURATION:
        raise ValueError("Video duration exceeds limit or is invalid")
    # Keep original bytes; only accept MP4 containers for the existing MP4 player.
    if "mp4" not in info.get("format", {}).get("format_name", "").split(","):
        raise ValueError("Export the video as MP4 before importing")
    return {"duration": duration, "has_audio": any(s.get("codec_type") == "audio" for s in streams)}


async def store_import(upload, metadata: ImportMetadata, directory: Path) -> dict:
    directory.mkdir(parents=True, exist_ok=False)
    temporary = directory / "upload.part"
    digest = hashlib.sha256()
    size = 0
    with temporary.open("wb") as handle:
        while chunk := await upload.read(1024 * 1024):
            size += len(chunk)
            if size > settings.MAX_IMPORT_BYTES:
                raise OverflowError("Video exceeds upload limit")
            digest.update(chunk)
            handle.write(chunk)
    media = await probe_media(temporary)
    fields = metadata.model_dump(exclude={"rights_confirmed", "rights_note", "language"})
    meta = VideoMeta(**fields, duration=media["duration"])
    manifest = {
        "schema_version": 1, "video_meta": meta.model_dump(mode="json"),
        "language": metadata.language, "rights_confirmed": True,
        "rights_note": metadata.rights_note, "sha256": digest.hexdigest(),
        "size_bytes": size, "has_audio": media["has_audio"],
    }
    temporary.rename(directory / "video.mp4")
    (directory / "import.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest

"""Upload first, explicitly start analysis later."""
import asyncio
import json
import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile
from pydantic import ValidationError

from config import settings
from models.schemas import ImportMetadata, ImportedAnalysisRequest, VideoMeta
from routers.analyze import tasks
from services.importer import store_import
from services.pipeline import run_pipeline

router = APIRouter()


def import_directory(import_id: str) -> Path:
    try:
        if str(uuid.UUID(import_id)) != import_id:
            raise ValueError()
    except ValueError:
        raise HTTPException(404, "Import not found")
    return Path(settings.DATA_DIR) / import_id


@router.post("/api/imports", status_code=201)
async def import_video(file: UploadFile = File(...), metadata: str = Form(...)):
    directory = None
    try:
        if len(metadata.encode("utf-8")) > 16384:
            raise ValueError("Metadata exceeds 16 KiB")
        sidecar = ImportMetadata.model_validate_json(metadata)
        import_id = str(uuid.uuid4())
        directory = import_directory(import_id)
        manifest = await store_import(file, sidecar, directory)
        return {"import_id": import_id, "status": "imported", **manifest}
    except OverflowError as exc:
        raise HTTPException(413, str(exc))
    except (ValueError, ValidationError) as exc:
        raise HTTPException(422, str(exc))
    except (FileNotFoundError, asyncio.TimeoutError):
        raise HTTPException(503, "FFprobe unavailable or timed out")
    finally:
        await file.close()
        if directory and not (directory / "import.json").exists():
            shutil.rmtree(directory, ignore_errors=True)


@router.post("/api/imports/{import_id}/analyze", status_code=202)
async def analyze_import(import_id: str, req: ImportedAnalysisRequest, background_tasks: BackgroundTasks):
    directory = import_directory(import_id)
    if not (directory / "import.json").is_file():
        raise HTTPException(404, "Import not found")
    if not req.allow_paid_models:
        raise HTTPException(409, "Analysis calls paid models; set allow_paid_models=true explicitly")
    if import_id in tasks:
        raise HTTPException(409, "Analysis already submitted")
    manifest = json.loads((directory / "import.json").read_text(encoding="utf-8"))
    queue = asyncio.Queue()
    tasks[import_id] = {"status": "queued", "events": queue}
    background_tasks.add_task(
        run_pipeline, import_id, "", queue,
        imported_meta=VideoMeta(**manifest["video_meta"]), language=manifest["language"],
    )
    return {"task_id": import_id, "status": "queued"}

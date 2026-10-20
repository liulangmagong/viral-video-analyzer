import asyncio
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from fastapi.testclient import TestClient
from main import app
from config import settings
from models.schemas import VideoMeta, FrameAnalysis, ViralAnalysis
from routers.analyze import tasks
from services.pipeline import run_pipeline
from services.transcriber import transcribe_with_whisper
from services.video_processor import extract_audio, extract_frames


class ImportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.video = Path(cls.tmp.name) / "sample.mp4"
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=blue:s=64x64:d=4", "-c:v", "mpeg4", str(cls.video)], check=True)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def setUp(self):
        self.data = tempfile.TemporaryDirectory()
        self.old_dir = settings.DATA_DIR
        settings.DATA_DIR = self.data.name
        self.client = TestClient(app)
        tasks.clear()
        self.meta = {"platform": "tiktok", "title": "Jeans", "views": 660000, "likes": 112000,
                     "metrics_source": "vid2prompt email", "metrics_are_estimates": True,
                     "rights_confirmed": True, "rights_note": "Creator licensed analysis"}

    def tearDown(self):
        settings.DATA_DIR = self.old_dir
        self.data.cleanup()

    def upload(self, content=None, meta=None):
        return self.client.post("/api/imports", files={"file": ("../../unsafe.mp4", self.video.read_bytes() if content is None else content)}, data={"metadata": json.dumps(self.meta if meta is None else meta)})

    def test_import_preserves_bytes_and_metrics_without_models(self):
        with patch("services.pipeline.download_video", new_callable=AsyncMock) as download, patch("services.pipeline.analyze_frame", new_callable=AsyncMock) as model:
            result = self.upload()
            self.assertEqual(result.status_code, 201, result.text)
            body = result.json()
            self.assertEqual(body["video_meta"]["views"], 660000)
            self.assertEqual(body["video_meta"]["duration"], 4)
            self.assertIsNone(body["language"])
            self.assertFalse(body["has_audio"])
            self.assertEqual((Path(settings.DATA_DIR)/body["import_id"]/"video.mp4").read_bytes(), self.video.read_bytes())
            download.assert_not_called(); model.assert_not_called()
            self.assertEqual(self.client.post(f'/api/imports/{body["import_id"]}/analyze', json={}).status_code, 409)
            self.assertEqual(tasks, {})

    def test_invalid_media_cleanup(self):
        self.assertEqual(self.upload(b"not a video").status_code, 422)
        self.assertEqual(list(Path(settings.DATA_DIR).iterdir()), [])

    def test_metadata_validation(self):
        for extra in ({"likes": -1}, {"rights_confirmed": False}, {"unexpected": 1}, {"views": "many"}):
            with self.subTest(extra=extra):
                self.assertEqual(self.upload(meta={**self.meta, **extra}).status_code, 422)

    def test_size_limit_cleanup(self):
        with patch.object(settings, "MAX_IMPORT_BYTES", 4):
            self.assertEqual(self.upload().status_code, 413)
        self.assertEqual(list(Path(settings.DATA_DIR).iterdir()), [])

    def test_probe_missing_cleanup(self):
        with patch("services.importer.probe_media", side_effect=FileNotFoundError):
            self.assertEqual(self.upload().status_code, 503)
        self.assertEqual(list(Path(settings.DATA_DIR).iterdir()), [])

    def test_real_ffmpeg_silent_media(self):
        self.assertIsNone(asyncio.run(extract_audio(str(self.video), self.data.name)))
        self.assertTrue(asyncio.run(extract_frames(str(self.video), str(Path(self.data.name)/"frames"))))

    def test_explicit_analysis_uses_manifest_and_existing_stream(self):
        body = self.upload().json()
        with patch("routers.imports.run_pipeline", new_callable=AsyncMock) as run:
            url = f'/api/imports/{body["import_id"]}/analyze'
            self.assertEqual(self.client.post(url, json={"allow_paid_models": True}).status_code, 202)
            self.assertEqual(run.call_args.kwargs["imported_meta"].platform, "tiktok")
            self.assertIsNone(run.call_args.kwargs["language"])
            self.assertEqual(self.client.post(url, json={"allow_paid_models": True}).status_code, 409)

    def test_pipeline_import_bypasses_downloader_and_silent_asr(self):
        async def check(imported):
            queue = asyncio.Queue()
            meta = VideoMeta(title="test", duration=4)
            with patch("services.pipeline.download_video", new_callable=AsyncMock, return_value=meta) as download, patch("services.pipeline.extract_audio", new_callable=AsyncMock, return_value=None), patch("services.pipeline.extract_frames", new_callable=AsyncMock, return_value=[{"path":"mock.jpg","timestamp":0}]), patch("services.pipeline.transcribe_with_whisper", new_callable=AsyncMock) as asr, patch("services.pipeline.analyze_frame", new_callable=AsyncMock, return_value=FrameAnalysis(timestamp=0, frame_path="mock.jpg")), patch("services.pipeline.generate_segment_prompts", new_callable=AsyncMock, return_value={}), patch("services.pipeline.analyze_viral", new_callable=AsyncMock, return_value=ViralAnalysis()):
                await run_pipeline("test", "douyin-url", queue, imported_meta=meta if imported else None)
                self.assertEqual(download.await_count, 0 if imported else 1)
                asr.assert_not_called()
                events = []
                while not queue.empty(): events.append(await queue.get())
                self.assertEqual(events[-1]["type"], "done", events)
        asyncio.run(check(True)); asyncio.run(check(False))

    def test_original_douyin_route_unchanged(self):
        with patch("routers.analyze.run_pipeline", new_callable=AsyncMock) as run:
            res = self.client.post("/api/analyze", json={"url": "https://www.douyin.com/video/123", "detail": {"aweme_detail": {}}})
            self.assertEqual(res.status_code, 200)
            self.assertEqual(run.call_args.args[1], "https://www.douyin.com/video/123")

    def test_tiktok_url_fails_before_task_creation(self):
        self.assertEqual(self.client.post("/api/analyze", json={"url": "https://www.tiktok.com/@a/video/123"}).status_code, 422)
        self.assertEqual(tasks, {})

    def test_language_forwarding(self):
        with patch("services.transcriber._run_whisper_sync", return_value=[]) as transcribe:
            asyncio.run(transcribe_with_whisper("fake.wav", language=None))
            transcribe.assert_called_once_with("fake.wav", None)


if __name__ == "__main__":
    unittest.main()

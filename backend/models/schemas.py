from pydantic import BaseModel, ConfigDict, Field
from typing import Optional, Literal
from datetime import datetime


class AnalyzeRequest(BaseModel):
    url: str


class AnalyzeResponse(BaseModel):
    task_id: str
    status: str


class VideoMeta(BaseModel):
    platform: str = "douyin"
    source_url: Optional[str] = None
    source_video_id: Optional[str] = None
    views: Optional[int] = None
    metrics_source: Optional[str] = None
    metrics_observed_at: Optional[datetime] = None
    metrics_are_estimates: bool = False

    title: str = ""
    author: str = ""
    author_id: str = ""
    likes: Optional[int] = None
    comments: Optional[int] = None
    shares: Optional[int] = None
    duration: float = 0.0
    thumbnail_url: Optional[str] = None


class TranscriptWord(BaseModel):
    word: str
    start: float
    end: float


class TranscriptSegment(BaseModel):
    text: str
    start: float
    end: float
    words: list[TranscriptWord] = []


class FrameAnalysis(BaseModel):
    timestamp: float
    frame_path: str
    shot_type: str = ""
    camera_movement: str = ""
    composition: str = ""
    transition: str = ""
    text_overlay: Optional[str] = None
    visual_description: str = ""
    mood: str = ""
    key_elements: list[str] = []


class AIPrompts(BaseModel):
    visual: str = ""
    copywriting: str = ""
    recreation: str = ""


class SegmentAnalysis(BaseModel):
    start_time: float
    end_time: float
    frames: list[FrameAnalysis] = []
    transcript: Optional[str] = None
    ai_prompts: AIPrompts = AIPrompts()


class ViralAnalysis(BaseModel):
    hook_score: int = 0
    hook_analysis: str = ""
    pacing_analysis: str = ""
    emotional_arc: str = ""
    key_viral_factors: list[str] = []
    target_audience: str = ""
    content_formula: str = ""
    recreation_blueprint: str = ""


class FullAnalysisResult(BaseModel):
    task_id: str
    video_meta: VideoMeta = VideoMeta()
    transcript: list[TranscriptSegment] = []
    segments: list[SegmentAnalysis] = []
    viral_analysis: ViralAnalysis = ViralAnalysis()
    created_at: str = ""


class ImportMetadata(BaseModel):
    """Sidecar contract; duration is always probed from the actual media."""
    model_config = ConfigDict(extra="forbid")
    platform: Literal["tiktok", "douyin", "local"] = "local"
    title: str = Field(default="", max_length=2000)
    author: str = Field(default="", max_length=200)
    author_id: str = Field(default="", max_length=200)
    source_url: Optional[str] = Field(default=None, max_length=2048)
    source_video_id: Optional[str] = Field(default=None, max_length=200)
    likes: Optional[int] = Field(default=None, ge=0, strict=True)
    comments: Optional[int] = Field(default=None, ge=0, strict=True)
    shares: Optional[int] = Field(default=None, ge=0, strict=True)
    views: Optional[int] = Field(default=None, ge=0, strict=True)
    metrics_source: Optional[str] = Field(default=None, max_length=500)
    metrics_observed_at: Optional[datetime] = None
    metrics_are_estimates: bool = False
    language: Optional[str] = Field(default=None, pattern=r"^[a-z]{2,3}$")
    rights_confirmed: Literal[True]
    rights_note: str = Field(min_length=1, max_length=2000)


class ImportedAnalysisRequest(BaseModel):
    allow_paid_models: bool = False

from enum import Enum
from pathlib import Path
from typing import Optional
from pydantic import BaseModel, Field

class JobStatus(str, Enum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    SKIPPED = "SKIPPED"
    FAILED = "FAILED"
    HW_CAP_LIMIT = "HW_CAP_LIMIT"

class VideoMetadata(BaseModel):
    width: int
    height: int
    codec: str
    fps: float
    camera_model: Optional[str] = None
    bitrate_kbps: Optional[float] = None

class VideoFile(BaseModel):
    path: Path
    size_bytes: int
    metadata: Optional[VideoMetadata] = None

class CompressionJob(BaseModel):
    source_file: VideoFile
    status: JobStatus = JobStatus.PENDING
    output_path: Optional[Path] = None
    error_message: Optional[str] = None
    duration_seconds: Optional[float] = None

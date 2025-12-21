from typing import Optional
from pathlib import Path
from pydantic import BaseModel
from .models import CompressionJob

class Event(BaseModel):
    """Base class for all domain events."""
    pass

class JobEvent(Event):
    job: CompressionJob

class JobStarted(JobEvent):
    pass

class JobProgressUpdated(JobEvent):
    progress_percent: float

class JobCompleted(JobEvent):
    pass

class JobFailed(JobEvent):
    error_message: str

class HardwareCapabilityExceeded(JobEvent):
    pass

class DiscoveryStarted(Event):
    directory: Path

class DiscoveryFinished(Event):
    files_found: int

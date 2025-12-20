from typing import Optional
from pathlib import Path
from .events import Event
from .models import CompressionJob

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

class DiscoveryStarted(Event):
    directory: Path

class DiscoveryFinished(Event):
    files_found: int
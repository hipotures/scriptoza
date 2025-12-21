from typing import Optional, List, TYPE_CHECKING
from pathlib import Path
from pydantic import BaseModel
from .models import CompressionJob

if TYPE_CHECKING:
    from .models import VideoFile

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
    files_to_process: int = 0
    already_compressed: int = 0
    ignored_small: int = 0
    ignored_err: int = 0
    ignored_av1: int = 0

class QueueUpdated(Event):
    pending_files: List  # List[VideoFile] but avoid circular import

class RefreshRequested(Event):
    """Event to trigger re-scanning for new files."""
    pass

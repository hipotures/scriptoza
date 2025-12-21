import pytest
from pathlib import Path
from unittest.mock import MagicMock
from vbc.infrastructure.event_bus import EventBus
from vbc.ui.state import UIState
from vbc.ui.manager import UIManager
from vbc.domain.events import JobStarted, JobCompleted
from vbc.domain.models import VideoFile, CompressionJob, JobStatus

def test_ui_manager_updates_state_on_event(tmp_path):
    bus = EventBus()
    state = UIState()
    manager = UIManager(bus, state)
    
    vf = VideoFile(path=Path("test.mp4"), size_bytes=1000)
    job = CompressionJob(source_file=vf, status=JobStatus.PROCESSING)
    
    # 1. Start event
    bus.publish(JobStarted(job=job))
    assert len(state.active_jobs) == 1
    
    # 2. Complete event
    # Mock file for size calculation
    out_file = tmp_path / "out.mp4"
    out_file.write_text("a" * 100) # 100 bytes
    job.output_path = out_file
    
    bus.publish(JobCompleted(job=job))
    assert len(state.active_jobs) == 0
    assert state.completed_count == 1
    assert state.total_output_bytes == 100

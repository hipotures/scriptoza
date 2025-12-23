from datetime import datetime, timedelta

import pytest
from rich.console import Group
from rich.panel import Panel
from rich.table import Table

from vbc.domain.models import CompressionJob, JobStatus, VideoFile, VideoMetadata
from vbc.ui.state import UIState
from vbc.ui import dashboard as dashboard_module
from vbc.ui.dashboard import Dashboard

def test_dashboard_initialization():
    """Test that Dashboard can be initialized with UIState."""
    state = UIState()
    dashboard = Dashboard(state)
    assert dashboard.state is state

def test_dashboard_context_manager():
    """Test that Dashboard can be used as context manager."""
    state = UIState()
    dashboard = Dashboard(state)
    # Dashboard should have __enter__ and __exit__ for context manager protocol
    assert hasattr(dashboard, '__enter__')
    assert hasattr(dashboard, '__exit__')


def test_dashboard_format_helpers():
    state = UIState()
    dashboard = Dashboard(state)

    assert dashboard.format_size(0) == "0B"
    assert dashboard.format_size(1024) == "1.0KB"
    assert dashboard.format_time(59) == "59s"
    assert dashboard.format_time(61) == "01m 01s"
    assert dashboard.format_time(3661) == "1h 01m"

    metadata = VideoMetadata(width=1920, height=1080, codec="h264", fps=29.97)
    assert dashboard.format_resolution(metadata) == "2M"
    assert dashboard.format_fps(metadata) == "29fps"

    state.strip_unicode_display = True
    assert dashboard._sanitize_filename("cafe\u00e9") == "cafe"
    assert dashboard._sanitize_filename("\U0001F3A5 2023-12-09") == "2023-12-09"
    state.strip_unicode_display = False
    assert dashboard._sanitize_filename("cafe\u00e9") == "cafe\u00e9"


def test_dashboard_format_kv_line():
    dashboard = Dashboard(UIState())
    formatted = dashboard._format_kv_line("Key: Value")
    assert "[grey70]Key:[/]" in formatted
    assert "Value" in formatted


def test_dashboard_panels_with_state(tmp_path):
    state = UIState()
    state.completed_count = 2
    state.failed_count = 1
    state.skipped_count = 1
    state.hw_cap_count = 1
    state.cam_skipped_count = 1
    state.min_ratio_skip_count = 1
    state.discovery_finished = True
    state.files_to_process = 4
    state.already_compressed_count = 1
    state.ignored_small_count = 1
    state.ignored_err_count = 1
    state.ignored_av1_count = 1
    state.processing_start_time = datetime.now() - timedelta(seconds=10)
    state.total_input_bytes = 10 * 1024 * 1024

    dashboard = Dashboard(state)
    status_panel = dashboard._generate_status_panel()
    assert isinstance(status_panel, Panel)
    assert "Files to compress" in str(status_panel.renderable)

    progress_panel = dashboard._generate_progress_panel()
    assert isinstance(progress_panel, Panel)
    assert "ETA:" in str(progress_panel.renderable)

    source = tmp_path / "video.mp4"
    source.write_bytes(b"x" * 100)
    vf = VideoFile(path=source, size_bytes=source.stat().st_size, metadata=VideoMetadata(width=1280, height=720, codec="h264", fps=30.0))
    job = CompressionJob(source_file=vf, status=JobStatus.PROCESSING, rotation_angle=180)
    state.active_jobs = [job]
    state.job_start_times[vf.path.name] = datetime.now() - timedelta(seconds=5)

    processing_panel = dashboard._generate_processing_panel()
    assert isinstance(processing_panel.renderable, Table)

    completed_job = CompressionJob(source_file=vf, status=JobStatus.COMPLETED, output_path=tmp_path / "out.mp4")
    completed_job.output_size_bytes = 90
    completed_job.duration_seconds = 2.0
    completed_job.error_message = "Ratio 0.95 above threshold, kept original"
    state.recent_jobs.appendleft(completed_job)

    recent_panel = dashboard._generate_recent_panel()
    assert isinstance(recent_panel.renderable, Table)

    state.pending_files = [vf]
    queue_panel = dashboard._generate_queue_panel()
    assert isinstance(queue_panel.renderable, Table)

    summary_panel = dashboard._generate_summary_panel()
    assert isinstance(summary_panel, Panel)
    assert "success" in str(summary_panel.renderable)


def test_dashboard_create_display_overlay():
    state = UIState()
    state.show_config = True
    state.config_lines = ["Threads: 2", "Encoder: SVT-AV1 (CPU)"]
    dashboard = Dashboard(state)

    display = dashboard.create_display()
    assert isinstance(display, dashboard_module._Overlay)

    state.show_config = False
    display = dashboard.create_display()
    assert isinstance(display, Group)


def test_dashboard_start_stop(monkeypatch):
    state = UIState()
    dashboard = Dashboard(state)

    class DummyLive:
        def __init__(self, *_args, **_kwargs):
            self.started = False
            self.stopped = False
            self.updated = []

        def start(self):
            self.started = True

        def stop(self):
            self.stopped = True

        def update(self, display):
            self.updated.append(display)

    def fake_refresh_loop(self):
        self._stop_refresh.set()

    monkeypatch.setattr(dashboard_module, "Live", DummyLive)
    monkeypatch.setattr(Dashboard, "_refresh_loop", fake_refresh_loop)

    dashboard.start()
    assert isinstance(dashboard._live, DummyLive)
    assert dashboard._live.started
    dashboard.stop()
    assert dashboard._live.stopped

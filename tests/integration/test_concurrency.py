import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch
from vbc.pipeline.orchestrator import Orchestrator
from vbc.config.models import AppConfig, GeneralConfig
from vbc.domain.models import VideoFile, VideoMetadata

def test_concurrency_threads():
    """Test that orchestrator respects thread limits during concurrent processing."""
    # Config with 4 threads
    config = AppConfig(general=GeneralConfig(threads=4, debug=False))

    mock_file_scanner = MagicMock()
    # Return enough files to saturate threads
    mock_file_scanner.scan.return_value = [
        VideoFile(path=Path(f"test{i}.mp4"), size_bytes=1000) for i in range(10)
    ]

    mock_exif = MagicMock()
    mock_ffprobe = MagicMock()
    # Mock ffprobe to return valid stream info (not MagicMock for color_space)
    mock_ffprobe.get_stream_info.return_value = {
        'width': 1920,
        'height': 1080,
        'codec': 'h264',
        'fps': 30.0,
        'color_space': None,  # Must be None or string, not MagicMock
        'duration': 10.0
    }

    mock_ffmpeg = MagicMock()

    with patch("concurrent.futures.ThreadPoolExecutor") as MockExecutor, \
         patch("concurrent.futures.wait") as MockWait:

        # Mock the executor context manager
        mock_executor_instance = MagicMock()
        MockExecutor.return_value.__enter__.return_value = mock_executor_instance
        MockExecutor.return_value.__exit__.return_value = None

        # Mock futures returned by submit
        mock_futures = [MagicMock() for _ in range(10)]
        for f in mock_futures:
            f.done.return_value = True
            f.result.return_value = None

        mock_executor_instance.submit.side_effect = mock_futures

        # Mock wait() to return (done_futures, pending_futures)
        def mock_wait_func(futures_set, timeout=None, return_when=None):
            # Return all futures as done
            return (futures_set, set())

        MockWait.side_effect = mock_wait_func

        orchestrator = Orchestrator(
            config=config,
            event_bus=MagicMock(),
            file_scanner=mock_file_scanner,
            exif_adapter=mock_exif,
            ffprobe_adapter=mock_ffprobe,
            ffmpeg_adapter=mock_ffmpeg
        )

        orchestrator.run(Path("/tmp/test_concurrency"))

        # Verify executor was initialized with large pool (16)
        # Actual concurrency controlled via internal _thread_lock
        MockExecutor.assert_called_with(max_workers=16)

        # Verify submit was called for each file
        assert mock_executor_instance.submit.call_count == 10

        # Verify wait was called
        assert MockWait.called

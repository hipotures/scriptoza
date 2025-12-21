import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch
from vbc.pipeline.orchestrator import Orchestrator
from vbc.config.models import AppConfig, GeneralConfig
from vbc.domain.models import VideoFile, VideoMetadata

def test_concurrency_threads():
    # Config with 4 threads
    config = AppConfig(general=GeneralConfig(threads=4))
    
    mock_file_scanner = MagicMock()
    # Return enough files to saturate threads
    mock_file_scanner.scan.return_value = [
        VideoFile(path=Path(f"test{i}.mp4"), size_bytes=1000) for i in range(10)
    ]
    
    mock_exif = MagicMock()
    mock_exif.extract_metadata.return_value = VideoMetadata(width=1920, height=1080, codec="h264", fps=30)
    
    with patch("concurrent.futures.ThreadPoolExecutor") as MockExecutor, \
         patch("concurrent.futures.wait") as MockWait:
        orchestrator = Orchestrator(
            config=config,
            event_bus=MagicMock(),
            file_scanner=mock_file_scanner,
            exif_adapter=mock_exif,
            ffprobe_adapter=MagicMock(),
            ffmpeg_adapter=MagicMock()
        )
        
        orchestrator.run(Path("/tmp"))
        
        # Verify executor was initialized with large pool (16)
        # Actual concurrency controlled via internal _thread_lock
        MockExecutor.assert_called_with(max_workers=16)
        
        # Verify submit was called for each file
        # When using 'with MockExecutor() as executor', the instance returned by __enter__ is what counts
        instance = MockExecutor.return_value.__enter__.return_value
        assert instance.submit.call_count == 10
        
        # Verify wait was called
        assert MockWait.called

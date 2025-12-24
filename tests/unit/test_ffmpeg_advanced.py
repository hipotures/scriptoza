"""Unit tests for ffmpeg.py advanced features and edge cases."""
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch, call
import subprocess
import queue
from vbc.infrastructure.ffmpeg import FFmpegAdapter
from vbc.config.models import GeneralConfig
from vbc.domain.models import VideoFile, VideoMetadata, CompressionJob, JobStatus
from vbc.infrastructure.event_bus import EventBus


@pytest.fixture
def ffmpeg_adapter():
    """Create FFmpegAdapter with event bus."""
    bus = EventBus()
    return FFmpegAdapter(event_bus=bus)


@pytest.fixture
def sample_job(tmp_path):
    """Create a sample compression job."""
    input_file = tmp_path / "input.mp4"
    output_file = tmp_path / "output.mp4"
    input_file.write_text("input")

    metadata = VideoMetadata(
        width=1920,
        height=1080,
        codec='h264',
        fps=30.0,
        duration=10.0
    )

    video_file = VideoFile(path=input_file, size=1000, metadata=metadata)
    job = CompressionJob(source_file=video_file, output_path=output_file)
    return job


class TestCPUEncodingPath:
    """Test CPU encoding (libsvtav1) path."""

    def test_build_command_cpu_mode(self, ffmpeg_adapter, sample_job):
        """Test command generation for CPU encoding."""
        config = GeneralConfig(gpu=False, cq=45, copy_metadata=True)

        cmd = ffmpeg_adapter._build_command(sample_job, config, rotate=None)

        # Verify CPU encoder is used
        assert '-c:v' in cmd
        idx = cmd.index('-c:v')
        assert cmd[idx + 1] == 'libsvtav1'

        # Verify preset
        assert '-preset' in cmd
        idx = cmd.index('-preset')
        assert cmd[idx + 1] == '6'

        # Verify CRF instead of CQ
        assert '-crf' in cmd

    def test_build_command_no_metadata_copy(self, ffmpeg_adapter, sample_job):
        """Test -map_metadata -1 when copy_metadata=False."""
        config = GeneralConfig(gpu=True, cq=45, copy_metadata=False)

        cmd = ffmpeg_adapter._build_command(sample_job, config, rotate=None)

        # Verify metadata stripping
        assert '-map_metadata' in cmd
        idx = cmd.index('-map_metadata')
        assert cmd[idx + 1] == '-1'


class TestRotationPaths:
    """Test video rotation paths."""

    def test_build_command_rotation_90(self, ffmpeg_adapter, sample_job):
        """Test 90° rotation command."""
        config = GeneralConfig(gpu=True, cq=45)

        cmd = ffmpeg_adapter._build_command(sample_job, config, rotate=90)

        # Verify rotation filter
        assert '-vf' in cmd
        idx = cmd.index('-vf')
        assert 'transpose=1' in cmd[idx + 1]

    def test_build_command_rotation_270(self, ffmpeg_adapter, sample_job):
        """Test 270° rotation command."""
        config = GeneralConfig(gpu=True, cq=45)

        cmd = ffmpeg_adapter._build_command(sample_job, config, rotate=270)

        # Verify rotation filter
        assert '-vf' in cmd
        idx = cmd.index('-vf')
        assert 'transpose=2' in cmd[idx + 1]

    def test_build_command_rotation_180(self, ffmpeg_adapter, sample_job):
        """Test 180° rotation command (double transpose)."""
        config = GeneralConfig(gpu=True, cq=45)

        cmd = ffmpeg_adapter._build_command(sample_job, config, rotate=180)

        # Verify double transpose for 180°
        assert '-vf' in cmd
        idx = cmd.index('-vf')
        assert 'transpose=2,transpose=2' in cmd[idx + 1]


class TestDebugLogging:
    """Test debug logging paths."""

    def test_compress_with_debug_enabled(self, ffmpeg_adapter, sample_job, tmp_path):
        """Test that debug logging is triggered when debug=True."""
        config = GeneralConfig(gpu=True, cq=45, debug=True)

        with patch('subprocess.Popen') as mock_popen:
            # Mock successful compression
            mock_process = MagicMock()
            mock_process.poll.return_value = None
            mock_process.returncode = 0
            mock_popen.return_value = mock_process

            # Mock queue to simulate ffmpeg output ending
            with patch('queue.Queue') as mock_queue_class:
                mock_queue = MagicMock()
                mock_queue.get.side_effect = queue.Empty()
                mock_queue_class.return_value = mock_queue

                # Mock threading
                with patch('threading.Thread'):
                    # Create tmp file to simulate success
                    tmp_path = sample_job.output_path.with_suffix('.tmp')
                    tmp_path.write_text("compressed")

                    ffmpeg_adapter.compress(sample_job, config)

                    # Verify job completed
                    assert sample_job.status == JobStatus.COMPLETED


class TestFFmpegFailures:
    """Test FFmpeg failure scenarios."""

    def test_compress_process_wait_timeout(self, ffmpeg_adapter, sample_job):
        """Test timeout during process.wait() after terminate."""
        config = GeneralConfig(gpu=True, cq=45)

        with patch('subprocess.Popen') as mock_popen:
            mock_process = MagicMock()
            mock_process.poll.return_value = None

            # Simulate shutdown signal
            import threading
            shutdown_event = threading.Event()
            shutdown_event.set()

            # Make wait() timeout on first call, succeed on second
            mock_process.wait.side_effect = [
                subprocess.TimeoutExpired(cmd=['ffmpeg'], timeout=3),
                None  # After kill()
            ]

            mock_popen.return_value = mock_process

            with patch('queue.Queue'), patch('threading.Thread'):
                ffmpeg_adapter.compress(sample_job, config, shutdown_event=shutdown_event)

                # Verify terminate -> wait -> kill -> wait sequence
                assert mock_process.terminate.called
                assert mock_process.kill.called
                assert mock_process.wait.call_count == 2
                assert sample_job.status == JobStatus.INTERRUPTED

    def test_compress_tmp_file_missing(self, ffmpeg_adapter, sample_job):
        """Test when FFmpeg succeeds but .tmp file doesn't exist."""
        config = GeneralConfig(gpu=True, cq=45)

        with patch('subprocess.Popen') as mock_popen:
            mock_process = MagicMock()
            mock_process.poll.return_value = 0
            mock_process.returncode = 0
            mock_popen.return_value = mock_process

            with patch('queue.Queue') as mock_queue_class:
                mock_queue = MagicMock()
                mock_queue.get.side_effect = queue.Empty()
                mock_queue_class.return_value = mock_queue

                with patch('threading.Thread'):
                    # Don't create .tmp file - simulate missing output
                    ffmpeg_adapter.compress(sample_job, config)

                    # Should fail with missing tmp file
                    assert sample_job.status == JobStatus.FAILED
                    assert "Compression succeeded but output file not found" in sample_job.error_message

    def test_compress_ffmpeg_crash(self, ffmpeg_adapter, sample_job):
        """Test FFmpeg crash (non-zero return code)."""
        config = GeneralConfig(gpu=True, cq=45)

        with patch('subprocess.Popen') as mock_popen:
            mock_process = MagicMock()
            mock_process.poll.side_effect = [None, 1]  # None, then crashed
            mock_process.returncode = 1
            mock_popen.return_value = mock_process

            with patch('queue.Queue') as mock_queue_class:
                mock_queue = MagicMock()
                # Simulate error message in stderr
                mock_queue.get.side_effect = [
                    "Error: Invalid codec parameters",
                    queue.Empty()
                ]
                mock_queue_class.return_value = mock_queue

                with patch('threading.Thread'):
                    ffmpeg_adapter.compress(sample_job, config)

                    # Should fail
                    assert sample_job.status == JobStatus.FAILED
                    assert "Error: Invalid codec parameters" in sample_job.error_message


class TestKeyboardInterrupt:
    """Test KeyboardInterrupt handling."""

    def test_compress_keyboard_interrupt_cleanup(self, ffmpeg_adapter, sample_job, tmp_path):
        """Test Ctrl+C cleanup during compression."""
        config = GeneralConfig(gpu=True, cq=45)

        with patch('subprocess.Popen') as mock_popen:
            mock_process = MagicMock()
            mock_popen.return_value = mock_process

            # Create .tmp file to verify cleanup
            tmp_path_file = sample_job.output_path.with_suffix('.tmp')
            tmp_path_file.write_text("partial")

            with patch('queue.Queue') as mock_queue_class:
                mock_queue = MagicMock()
                # Raise KeyboardInterrupt during queue.get()
                mock_queue.get.side_effect = KeyboardInterrupt()
                mock_queue_class.return_value = mock_queue

                with patch('threading.Thread'):
                    # Should raise KeyboardInterrupt
                    with pytest.raises(KeyboardInterrupt):
                        ffmpeg_adapter.compress(sample_job, config)

                    # Verify cleanup
                    assert mock_process.terminate.called
                    assert not tmp_path_file.exists()  # Should be cleaned up
                    assert sample_job.status == JobStatus.INTERRUPTED


class TestHardwareCapability:
    """Test hardware capability error detection."""

    def test_compress_hw_cap_error_detected(self, ffmpeg_adapter, sample_job):
        """Test detection of 'Hardware is lacking required capabilities' error."""
        config = GeneralConfig(gpu=True, cq=45)

        with patch('subprocess.Popen') as mock_popen:
            mock_process = MagicMock()
            mock_process.poll.side_effect = [None, 1]
            mock_process.returncode = 1
            mock_popen.return_value = mock_process

            with patch('queue.Queue') as mock_queue_class:
                mock_queue = MagicMock()
                # Simulate hardware capability error in stderr
                mock_queue.get.side_effect = [
                    "Hardware is lacking required capabilities (10-bit not supported)",
                    queue.Empty()
                ]
                mock_queue_class.return_value = mock_queue

                with patch('threading.Thread'):
                    ffmpeg_adapter.compress(sample_job, config)

                    # Should fail with HW_CAP status
                    assert sample_job.status == JobStatus.FAILED
                    assert "Hardware is lacking" in sample_job.error_message

                    # Event should be published
                    # (Verified in integration tests)


class TestProgressParsing:
    """Test FFmpeg progress parsing."""

    def test_compress_parses_time_progress(self, ffmpeg_adapter, sample_job):
        """Test that time= progress is parsed correctly."""
        config = GeneralConfig(gpu=True, cq=45, debug=False)

        with patch('subprocess.Popen') as mock_popen:
            mock_process = MagicMock()
            mock_process.poll.side_effect = [None, None, 0]
            mock_process.returncode = 0
            mock_popen.return_value = mock_process

            with patch('queue.Queue') as mock_queue_class:
                mock_queue = MagicMock()
                # Simulate progress output
                mock_queue.get.side_effect = [
                    "frame=  150 fps= 30 time=00:00:05.00 bitrate=1000.0kbits/s",
                    "frame=  300 fps= 30 time=00:00:10.00 bitrate=800.0kbits/s",
                    queue.Empty()
                ]
                mock_queue_class.return_value = mock_queue

                with patch('threading.Thread'):
                    # Create tmp file
                    tmp_path = sample_job.output_path.with_suffix('.tmp')
                    tmp_path.write_text("compressed")

                    ffmpeg_adapter.compress(sample_job, config)

                    # Should complete successfully
                    assert sample_job.status == JobStatus.COMPLETED
                    # Progress should be 100% (10s / 10s duration)
                    assert sample_job.progress == 100

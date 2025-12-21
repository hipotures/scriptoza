import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from vbc.infrastructure.ffmpeg import FFmpegAdapter
from vbc.domain.models import VideoFile, CompressionJob, JobStatus, VideoMetadata
from vbc.config.models import GeneralConfig

def test_ffmpeg_command_generation_gpu():
    config = GeneralConfig(threads=4, cq=45, gpu=True)
    vf = VideoFile(path=Path("input.mp4"), size_bytes=1000)
    job = CompressionJob(source_file=vf, output_path=Path("output.mp4"))

    adapter = FFmpegAdapter(event_bus=MagicMock())
    cmd = adapter._build_command(job, config)

    assert "ffmpeg" in cmd
    assert "-c:v" in cmd
    assert "av1_nvenc" in cmd
    assert "input.mp4" in cmd
    # FFmpeg writes to .tmp file first, then renames to .mp4
    assert "output.tmp" in cmd or any(".tmp" in str(c) for c in cmd)

def test_ffmpeg_command_generation_cpu():
    config = GeneralConfig(threads=4, cq=45, gpu=False)
    vf = VideoFile(path=Path("input.mp4"), size_bytes=1000)
    job = CompressionJob(source_file=vf, output_path=Path("output.mp4"))
    
    adapter = FFmpegAdapter(event_bus=MagicMock())
    cmd = adapter._build_command(job, config)
    
    assert "libsvtav1" in cmd

def test_ffmpeg_rotation():
    config = GeneralConfig(threads=4, cq=45, gpu=True)
    vf = VideoFile(path=Path("input.mp4"), size_bytes=1000)
    job = CompressionJob(source_file=vf, output_path=Path("output.mp4"))
    
    adapter = FFmpegAdapter(event_bus=MagicMock())
    # 180 degree rotation
    cmd = adapter._build_command(job, config, rotate=180)
    assert "transpose=2,transpose=2" in cmd

def test_ffmpeg_compress_success():
    config = GeneralConfig(threads=4, cq=45, gpu=True)
    vf = VideoFile(path=Path("input.mp4"), size_bytes=1000)
    job = CompressionJob(source_file=vf, output_path=Path("output.mp4"))
    
    with patch("subprocess.Popen") as mock_popen:
        process_instance = mock_popen.return_value
        process_instance.stdout = ["frame= 100 fps=10.0 q=45.0 Lsize= 100kB time=00:00:05.00 bitrate= 100.0kbits/s speed=1.0x"]
        process_instance.wait.return_value = 0
        process_instance.returncode = 0
        
        adapter = FFmpegAdapter(event_bus=MagicMock())
        adapter.compress(job, config)
        
        assert job.status == JobStatus.COMPLETED
        assert mock_popen.called

def test_ffmpeg_compress_failure():
    config = GeneralConfig(threads=4, cq=45, gpu=True)
    vf = VideoFile(path=Path("input.mp4"), size_bytes=1000)
    job = CompressionJob(source_file=vf, output_path=Path("output.mp4"))
    
    with patch("subprocess.Popen") as mock_popen:
        process_instance = mock_popen.return_value
        process_instance.stdout = ["Error message from ffmpeg"]
        process_instance.wait.return_value = 1
        process_instance.returncode = 1
        
        bus = MagicMock()
        adapter = FFmpegAdapter(event_bus=bus)
        adapter.compress(job, config)
        
        assert job.status == JobStatus.FAILED
        assert "ffmpeg exited with code 1" in job.error_message
        assert bus.publish.called
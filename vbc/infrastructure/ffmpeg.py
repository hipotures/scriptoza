import subprocess
import re
import logging
import time
from pathlib import Path
from typing import List, Optional
from vbc.domain.models import CompressionJob, JobStatus
from vbc.config.models import GeneralConfig
from vbc.infrastructure.event_bus import EventBus
from vbc.domain.events import JobProgressUpdated, JobFailed, HardwareCapabilityExceeded

class FFmpegAdapter:
    """Wrapper around ffmpeg for video compression."""

    def __init__(self, event_bus: EventBus):
        self.event_bus = event_bus
        self.logger = logging.getLogger(__name__)

    def _build_command(self, job: CompressionJob, config: GeneralConfig, rotate: Optional[int] = None) -> List[str]:
        """Constructs the ffmpeg command line arguments."""
        cmd = [
            "ffmpeg",
            "-y", # Overwrite output files
            "-i", str(job.source_file.path),
        ]
        
        # Video encoding settings
        if config.gpu:
            cmd.extend([
                "-c:v", "av1_nvenc",
                "-cq", str(config.cq),
                "-preset", "p7",
                "-tune", "hq"
            ])
        else:
            cmd.extend([
                "-c:v", "libsvtav1",
                "-preset", "6",
                "-crf", str(config.cq),
                "-svtav1-params", f"tune=0:enable-overlays=1"
            ])
            
        # Audio/Metadata settings
        cmd.extend([
            "-c:a", "copy",
            "-map_metadata", "0" if config.copy_metadata else "-1"
        ])
        
        # Rotation filter
        if rotate == 180:
            cmd.extend(["-vf", "transpose=2,transpose=2"])
        elif rotate == 90:
            cmd.extend(["-vf", "transpose=1"])
        elif rotate == 270:
            cmd.extend(["-vf", "transpose=2"])

        cmd.append(str(job.output_path))
        return cmd

    def compress(self, job: CompressionJob, config: GeneralConfig, rotate: Optional[int] = None):
        """Executes the compression process."""
        filename = job.source_file.path.name
        start_time = time.monotonic() if config.debug else None

        if config.debug:
            self.logger.info(f"FFMPEG_START: {filename} (gpu={config.gpu}, cq={config.cq})")

        cmd = self._build_command(job, config, rotate)

        # Use duration for progress calculation if available
        duration = job.source_file.metadata.bitrate_kbps if job.source_file.metadata else 0 # Placeholder for duration
        # Real duration should come from ffprobe/exiftool. Using a simple placeholder for now.

        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True,
            bufsize=1
        )
        
        # Regex to parse 'time=00:00:00.00' from ffmpeg output
        time_regex = re.compile(r"time=(\d+):(\d+):(\d+\.\d+)")
        hw_cap_error = False
        color_error = False
        
        for line in process.stdout:
            if "Hardware is lacking required capabilities" in line:
                hw_cap_error = True
            if "is not a valid value for color_primaries" in line or "is not a valid value for color_trc" in line:
                color_error = True

            match = time_regex.search(line)
            if match:
                # Calculate progress if duration is known (simplified)
                # For now, just emit that something happened or parse actual seconds
                h, m, s = map(float, match.groups())
                current_seconds = h * 3600 + m * 60 + s
                # self.event_bus.publish(JobProgressUpdated(job=job, progress_percent=...))
                
        process.wait()

        # Check for hardware capability error (code 187 or text match)
        if hw_cap_error or process.returncode == 187:
            job.status = JobStatus.HW_CAP_LIMIT
            job.error_message = "Hardware is lacking required capabilities"
            self.event_bus.publish(HardwareCapabilityExceeded(job=job))
            if config.debug and start_time:
                elapsed = time.monotonic() - start_time
                self.logger.info(f"FFMPEG_END: {filename} status=hw_cap_limit elapsed={elapsed:.2f}s")
        elif color_error:
            # Re-run with color fix remux (recursive call sets final status)
            if config.debug:
                self.logger.info(f"FFMPEG_COLORFIX: {filename} (applying color space fix)")
            self._apply_color_fix(job, config, rotate)
            # Status is now set by recursive compress() call, don't override
            if config.debug and start_time:
                elapsed = time.monotonic() - start_time
                self.logger.info(f"FFMPEG_END: {filename} status={job.status.value} elapsed={elapsed:.2f}s (with colorfix)")
        elif process.returncode != 0:
            job.status = JobStatus.FAILED
            job.error_message = f"ffmpeg exited with code {process.returncode}"
            self.event_bus.publish(JobFailed(job=job, error_message=job.error_message))
            if config.debug and start_time:
                elapsed = time.monotonic() - start_time
                self.logger.info(f"FFMPEG_END: {filename} status=failed code={process.returncode} elapsed={elapsed:.2f}s")
        else:
            job.status = JobStatus.COMPLETED
            if config.debug and start_time:
                elapsed = time.monotonic() - start_time
                self.logger.info(f"FFMPEG_END: {filename} status=completed elapsed={elapsed:.2f}s")

    def _apply_color_fix(self, job: CompressionJob, config: GeneralConfig, rotate: Optional[int]):
        """Special handling for FFmpeg 7.x 'reserved' color space bug."""
        # 1. Create a remuxed file with metadata filters
        color_fix_path = job.output_path.with_name(f"{job.output_path.stem}_colorfix.mp4")
        
        # Check if source is HEVC or H264 to apply correct bitstream filter
        # For simplicity we try to apply hevc_metadata then fallback
        remux_cmd = [
            "ffmpeg", "-y", "-i", str(job.source_file.path),
            "-c", "copy",
            "-bsf:v", "hevc_metadata=color_primaries=1:color_trc=1:colorspace=1",
            str(color_fix_path)
        ]
        
        res = subprocess.run(remux_cmd, capture_output=True)
        if res.returncode != 0:
            # Try H264 variant
            remux_cmd[5] = "h264_metadata=color_primaries=1:color_trc=1:colorspace=1"
            res = subprocess.run(remux_cmd, capture_output=True)
            
        if res.returncode == 0:
            # 2. Run compression using the colorfix file as input
            original_path = job.source_file.path
            job.source_file.path = color_fix_path
            try:
                self.compress(job, config, rotate)
            finally:
                # Cleanup and restore
                job.source_file.path = original_path
                if color_fix_path.exists():
                    color_fix_path.unlink()
        else:
            job.status = JobStatus.FAILED
            job.error_message = "Color fix remux failed"
            self.event_bus.publish(JobFailed(job=job, error_message=job.error_message))

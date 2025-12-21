import subprocess
import re
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
        
        for line in process.stdout:
            if "Hardware is lacking required capabilities" in line:
                hw_cap_error = True

            match = time_regex.search(line)
            if match:
                # Calculate progress if duration is known (simplified)
                # For now, just emit that something happened or parse actual seconds
                h, m, s = map(float, match.groups())
                current_seconds = h * 3600 + m * 60 + s
                # self.event_bus.publish(JobProgressUpdated(job=job, progress_percent=...))
                
        process.wait()
        
        if hw_cap_error:
            job.status = JobStatus.HW_CAP_LIMIT
            self.event_bus.publish(HardwareCapabilityExceeded(job=job))
        elif process.returncode != 0:
            job.status = JobStatus.FAILED
            job.error_message = f"ffmpeg exited with code {process.returncode}"
            self.event_bus.publish(JobFailed(job=job, error_message=job.error_message))
        else:
            job.status = JobStatus.COMPLETED

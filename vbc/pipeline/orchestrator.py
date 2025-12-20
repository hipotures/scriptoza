import re
from pathlib import Path
from typing import Optional
from vbc.config.models import AppConfig, GeneralConfig
from vbc.infrastructure.event_bus import EventBus
from vbc.infrastructure.file_scanner import FileScanner
from vbc.infrastructure.exif_tool import ExifToolAdapter
from vbc.infrastructure.ffprobe import FFprobeAdapter
from vbc.infrastructure.ffmpeg import FFmpegAdapter
from vbc.domain.models import CompressionJob, JobStatus, VideoFile
from vbc.domain.events import DiscoveryStarted, DiscoveryFinished, JobStarted, JobCompleted, JobFailed

class Orchestrator:
    def __init__(
        self,
        config: AppConfig,
        event_bus: EventBus,
        file_scanner: FileScanner,
        exif_adapter: ExifToolAdapter,
        ffprobe_adapter: FFprobeAdapter,
        ffmpeg_adapter: FFmpegAdapter
    ):
        self.config = config
        self.event_bus = event_bus
        self.file_scanner = file_scanner
        self.exif_adapter = exif_adapter
        self.ffprobe_adapter = ffprobe_adapter
        self.ffmpeg_adapter = ffmpeg_adapter

    def _determine_cq(self, file: VideoFile) -> int:
        """Determines the Constant Quality value based on camera model."""
        default_cq = self.config.general.cq if self.config.general.cq is not None else 45
        
        if not file.metadata or not file.metadata.camera_model:
            return default_cq
            
        model = file.metadata.camera_model
        # Check for partial matches in dynamic_cq keys
        for key, cq_value in self.config.general.dynamic_cq.items():
            if key in model:
                return cq_value
                
        return default_cq

    def _determine_rotation(self, file: VideoFile) -> Optional[int]:
        """Determines if rotation is needed based on filename pattern."""
        filename = file.path.name
        for pattern, angle in self.config.autorotate.patterns.items():
            if re.search(pattern, filename):
                return angle
        return None

    def run(self, input_dir: Path):
        self.event_bus.publish(DiscoveryStarted(directory=input_dir))
        
        # Scan for files
        files = list(self.file_scanner.scan(input_dir))
        self.event_bus.publish(DiscoveryFinished(files_found=len(files)))
        
        # Process sequentially for now
        for video_file in files:
            try:
                # 1. Metadata
                # Prefer ExifTool for deep metadata
                video_file.metadata = self.exif_adapter.extract_metadata(video_file)
                # Could merge with ffprobe info here if needed
                
                # 2. Decision Phase
                target_cq = self._determine_cq(video_file)
                rotation = self._determine_rotation(video_file)
                
                # Create a temporary config object for this job with specific settings
                # Ideally, we should clone config, but for now we pass parameters explicitly to adapter or create temp config
                job_config = self.config.general.model_copy()
                job_config.cq = target_cq
                
                # 3. Setup Job
                # Determine output path (simplified: append _out to input dir root, replicate structure)
                rel_path = video_file.path.relative_to(input_dir)
                output_dir = input_dir.with_name(f"{input_dir.name}_out")
                output_path = output_dir / rel_path
                output_path.parent.mkdir(parents=True, exist_ok=True)
                
                job = CompressionJob(
                    source_file=video_file,
                    output_path=output_path,
                    status=JobStatus.PENDING
                )
                
                # 4. Compress
                self.event_bus.publish(JobStarted(job=job))
                job.status = JobStatus.PROCESSING
                
                self.ffmpeg_adapter.compress(job, job_config, rotate=rotation)
                
                if job.status == JobStatus.COMPLETED:
                    self.event_bus.publish(JobCompleted(job=job))
                elif job.status == JobStatus.FAILED:
                    self.event_bus.publish(JobFailed(job=job, error_message=job.error_message or "Unknown error"))
                    
            except Exception as e:
                # Handle unexpected errors in loop
                print(f"Error processing {video_file.path}: {e}")
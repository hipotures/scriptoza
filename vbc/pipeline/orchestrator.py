from pathlib import Path
from vbc.config.models import AppConfig
from vbc.infrastructure.event_bus import EventBus
from vbc.infrastructure.file_scanner import FileScanner
from vbc.infrastructure.exif_tool import ExifToolAdapter
from vbc.infrastructure.ffprobe import FFprobeAdapter
from vbc.infrastructure.ffmpeg import FFmpegAdapter
from vbc.domain.models import CompressionJob, JobStatus
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
                
                # 2. Setup Job
                # Determine output path (simplified: append _out to input dir root, replicate structure)
                # For now, just a dummy output path relative to input
                rel_path = video_file.path.relative_to(input_dir)
                output_dir = input_dir.with_name(f"{input_dir.name}_out")
                output_path = output_dir / rel_path
                output_path.parent.mkdir(parents=True, exist_ok=True)
                
                job = CompressionJob(
                    source_file=video_file,
                    output_path=output_path,
                    status=JobStatus.PENDING
                )
                
                # 3. Compress
                self.event_bus.publish(JobStarted(job=job))
                job.status = JobStatus.PROCESSING
                
                # Decision logic (placeholder: use default config)
                self.ffmpeg_adapter.compress(job, self.config.general)
                
                if job.status == JobStatus.COMPLETED:
                    self.event_bus.publish(JobCompleted(job=job))
                elif job.status == JobStatus.FAILED:
                    self.event_bus.publish(JobFailed(job=job, error_message=job.error_message or "Unknown error"))
                    
            except Exception as e:
                # Handle unexpected errors in loop
                # In real impl, create a job for it to mark as failed?
                print(f"Error processing {video_file.path}: {e}")

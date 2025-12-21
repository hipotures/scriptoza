import re
import concurrent.futures
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

    def _process_file(self, video_file: VideoFile, input_dir: Path):
        """Processes a single file: Metadata -> Job -> Compress."""
        try:
            # 1. Metadata
            video_file.metadata = self.exif_adapter.extract_metadata(video_file)
            
            # 2. Decision Phase
            target_cq = self._determine_cq(video_file)
            rotation = self._determine_rotation(video_file)
            
            job_config = self.config.general.model_copy()
            job_config.cq = target_cq
            
            # 3. Setup Job
            try:
                rel_path = video_file.path.relative_to(input_dir)
            except ValueError:
                # Fallback if file is not strictly under input_dir (e.g. symlinks or weird paths)
                rel_path = video_file.path.name
                
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
            print(f"Error processing {video_file.path}: {e}")

    def run(self, input_dir: Path):
        self.event_bus.publish(DiscoveryStarted(directory=input_dir))
        
        # Scan for files
        files = list(self.file_scanner.scan(input_dir))
        self.event_bus.publish(DiscoveryFinished(files_found=len(files)))
        
        # Concurrent processing
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.config.general.threads) as executor:
            futures = [executor.submit(self._process_file, vf, input_dir) for vf in files]
            concurrent.futures.wait(futures)

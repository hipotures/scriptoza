import re
import threading
import concurrent.futures
from pathlib import Path
from typing import Optional, List
from vbc.config.models import AppConfig, GeneralConfig
from vbc.infrastructure.event_bus import EventBus
from vbc.infrastructure.file_scanner import FileScanner
from vbc.infrastructure.exif_tool import ExifToolAdapter
from vbc.infrastructure.ffprobe import FFprobeAdapter
from vbc.infrastructure.ffmpeg import FFmpegAdapter
from vbc.domain.models import CompressionJob, JobStatus, VideoFile
from vbc.domain.events import DiscoveryStarted, DiscoveryFinished, JobStarted, JobCompleted, JobFailed
from vbc.ui.keyboard import RequestShutdown, ThreadControlEvent

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
        
        # Dynamic control state
        self._shutdown_requested = False
        self._current_max_threads = config.general.threads
        self._active_threads = 0
        self._thread_lock = threading.Condition()
        
        self._setup_subscriptions()

    def _setup_subscriptions(self):
        self.event_bus.subscribe(RequestShutdown, self._on_shutdown_request)
        self.event_bus.subscribe(ThreadControlEvent, self._on_thread_control)

    def _on_shutdown_request(self, event: RequestShutdown):
        with self._thread_lock:
            self._shutdown_requested = True
            self._thread_lock.notify_all()

    def _on_thread_control(self, event: ThreadControlEvent):
        with self._thread_lock:
            new_val = self._current_max_threads + event.change
            self._current_max_threads = max(1, min(16, new_val))
            self._thread_lock.notify_all()

    def _determine_cq(self, file: VideoFile) -> int:
        """Determines the Constant Quality value based on camera model."""
        default_cq = self.config.general.cq if self.config.general.cq is not None else 45
        if not file.metadata or not file.metadata.camera_model:
            return default_cq
        model = file.metadata.camera_model
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
        """Processes a single file with dynamic concurrency control."""
        # 1. Acquire thread slot
        with self._thread_lock:
            while self._active_threads >= self._current_max_threads:
                self._thread_lock.wait()
            
            if self._shutdown_requested:
                return
                
            self._active_threads += 1

        try:
            # 2. Metadata & Decision
            video_file.metadata = self.exif_adapter.extract_metadata(video_file)
            target_cq = self._determine_cq(video_file)
            rotation = self._determine_rotation(video_file)
            
            job_config = self.config.general.model_copy()
            job_config.cq = target_cq
            
            try:
                rel_path = video_file.path.relative_to(input_dir)
            except ValueError:
                rel_path = video_file.path.name
                
            output_dir = input_dir.with_name(f"{input_dir.name}_out")
            output_path = output_dir / rel_path
            output_path.parent.mkdir(parents=True, exist_ok=True)
            
            job = CompressionJob(source_file=video_file, output_path=output_path)
            
            # 3. Compress
            self.event_bus.publish(JobStarted(job=job))
            job.status = JobStatus.PROCESSING
            self.ffmpeg_adapter.compress(job, job_config, rotate=rotation)
            
            if job.status == JobStatus.COMPLETED:
                self.event_bus.publish(JobCompleted(job=job))
            elif job.status == JobStatus.FAILED:
                self.event_bus.publish(JobFailed(job=job, error_message=job.error_message or "Unknown error"))
                
        except Exception as e:
            print(f"Error processing {video_file.path}: {e}")
        finally:
            with self._thread_lock:
                self._active_threads -= 1
                self._thread_lock.notify_all()

    def run(self, input_dir: Path):
        self.event_bus.publish(DiscoveryStarted(directory=input_dir))
        files = list(self.file_scanner.scan(input_dir))
        self.event_bus.publish(DiscoveryFinished(files_found=len(files)))
        
        # Use a large pool for the executor, but control actual concurrency via self._thread_lock
        # to allow real-time thread count changes.
        with concurrent.futures.ThreadPoolExecutor(max_workers=16) as executor:
            futures = []
            for vf in files:
                with self._thread_lock:
                    if self._shutdown_requested:
                        break
                futures.append(executor.submit(self._process_file, vf, input_dir))
            
            concurrent.futures.wait(futures)
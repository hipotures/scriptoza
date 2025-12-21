import re
import threading
import concurrent.futures
import shutil
from pathlib import Path
from typing import Optional, List
from vbc.config.models import AppConfig, GeneralConfig
from vbc.infrastructure.event_bus import EventBus
from vbc.infrastructure.file_scanner import FileScanner
from vbc.infrastructure.exif_tool import ExifToolAdapter
from vbc.infrastructure.ffprobe import FFprobeAdapter
from vbc.infrastructure.ffmpeg import FFmpegAdapter
from vbc.domain.models import CompressionJob, JobStatus, VideoFile
from vbc.domain.events import DiscoveryStarted, DiscoveryFinished, JobStarted, JobCompleted, JobFailed, QueueUpdated
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
        with self._thread_lock:
            while self._active_threads >= self._current_max_threads:
                self._thread_lock.wait()
            
            if self._shutdown_requested:
                return
                
            self._active_threads += 1

        try:
            # 1. Metadata & Decision
            video_file.metadata = self.exif_adapter.extract_metadata(video_file)
            
            if self.config.general.skip_av1 and video_file.metadata and "av1" in video_file.metadata.codec.lower():
                self.event_bus.publish(JobFailed(job=CompressionJob(source_file=video_file, status=JobStatus.SKIPPED), error_message="Already encoded in AV1"))
                return

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
            
            err_path = output_path.with_suffix(output_path.suffix + ".err")
            
            if err_path.exists():
                if self.config.general.clean_errors:
                    err_path.unlink()
                else:
                    self.event_bus.publish(JobFailed(job=CompressionJob(source_file=video_file, status=JobStatus.SKIPPED), error_message="Existing error marker found"))
                    return

            job = CompressionJob(source_file=video_file, output_path=output_path)
            
            # 2. Compress
            self.event_bus.publish(JobStarted(job=job))
            job.status = JobStatus.PROCESSING
            self.ffmpeg_adapter.compress(job, job_config, rotate=rotation)

            # Check final status after compression
            if job.status == JobStatus.COMPLETED:
                if output_path.exists():
                    out_size = output_path.stat().st_size
                    in_size = video_file.size_bytes
                    ratio = out_size / in_size
                    if ratio > (1.0 - self.config.general.min_compression_ratio):
                        shutil.copy2(video_file.path, output_path)
                        job.error_message = f"Ratio {ratio:.2f} above threshold, kept original"

                self.event_bus.publish(JobCompleted(job=job))
            elif job.status in (JobStatus.HW_CAP_LIMIT, JobStatus.FAILED):
                # Event already published by FFmpeg adapter, just write error marker
                with open(err_path, "w") as f:
                    f.write(job.error_message or "Unknown error")
            elif job.status == JobStatus.PROCESSING:
                # Status not updated - treat as unknown error
                job.status = JobStatus.FAILED
                job.error_message = "Compression finished but status not updated"
                with open(err_path, "w") as f:
                    f.write(job.error_message)
                self.event_bus.publish(JobFailed(job=job, error_message=job.error_message))

        except Exception as e:
            # Log exception but don't crash the thread
            import logging
            logging.error(f"Exception processing {video_file.path.name}: {e}")
            job.status = JobStatus.FAILED
            job.error_message = f"Exception: {str(e)}"
            with open(err_path, "w") as f:
                f.write(job.error_message)
            self.event_bus.publish(JobFailed(job=job, error_message=job.error_message))
        finally:
            with self._thread_lock:
                self._active_threads -= 1
                self._thread_lock.notify_all()

    def run(self, input_dir: Path):
        self.event_bus.publish(DiscoveryStarted(directory=input_dir))
        files = list(self.file_scanner.scan(input_dir))

        # Count files that will be skipped during discovery
        output_dir = input_dir.with_name(f"{input_dir.name}_out")
        already_compressed = 0
        ignored_err = 0
        ignored_av1 = 0
        files_to_process = []

        for vf in files:
            try:
                rel_path = vf.path.relative_to(input_dir)
            except ValueError:
                rel_path = vf.path.name
            output_path = output_dir / rel_path
            err_path = output_path.with_suffix(output_path.suffix + ".err")

            # Check for error markers FIRST (before timestamp check)
            if err_path.exists():
                if self.config.general.clean_errors:
                    err_path.unlink()  # Remove error marker
                else:
                    # Distinguish hw_cap errors from regular errors (like original vbc.py line 1636)
                    try:
                        err_content = err_path.read_text()
                        if "Hardware is lacking required capabilities" in err_content:
                            # hw_cap is not counted as "ignored_err" - it's hardware limit, not user error
                            pass
                        else:
                            ignored_err += 1
                    except:
                        ignored_err += 1
                    continue

            # Check if already compressed (output exists, is newer, and no error marker)
            if output_path.exists() and output_path.stat().st_mtime > vf.path.stat().st_mtime:
                already_compressed += 1
                continue

            # Check for AV1 (basic check, full metadata check happens during processing)
            if self.config.general.skip_av1:
                try:
                    stream_info = self.ffprobe_adapter.get_stream_info(vf.path)
                    if "av1" in stream_info.get("codec", "").lower():
                        ignored_av1 += 1
                        continue
                except:
                    pass  # If ffprobe fails, let the file be processed

            files_to_process.append(vf)

        self.event_bus.publish(DiscoveryFinished(
            files_found=len(files),
            files_to_process=len(files_to_process),
            already_compressed=already_compressed,
            ignored_small=0,  # Already filtered by scanner
            ignored_err=ignored_err,
            ignored_av1=ignored_av1
        ))

        # If no files to process, exit early
        if len(files_to_process) == 0:
            return

        # Prefetch metadata for queue display (like original vbc.py)
        for vf in files_to_process:
            if not vf.metadata:
                try:
                    vf.metadata = self.exif_adapter.extract_metadata(vf)
                except:
                    pass  # Ignore metadata errors for queue display

        # Submit-on-demand pattern (like original vbc.py)
        from collections import deque
        pending = deque(files_to_process)
        in_flight = {}  # future -> VideoFile

        # Update UI with initial pending files (store VideoFile objects, not just paths)
        self.event_bus.publish(QueueUpdated(pending_files=[vf for vf in pending]))

        with concurrent.futures.ThreadPoolExecutor(max_workers=16) as executor:
            def submit_batch():
                """Submit files up to max_inflight limit"""
                max_inflight = self.config.general.prefetch_factor * self._current_max_threads
                while len(in_flight) < max_inflight and pending and not self._shutdown_requested:
                    vf = pending.popleft()
                    future = executor.submit(self._process_file, vf, input_dir)
                    in_flight[future] = vf
                # Update UI with current pending files (store VideoFile objects, not just paths)
                self.event_bus.publish(QueueUpdated(pending_files=[vf for vf in pending]))

            # Initial batch submission
            submit_batch()

            # Process futures as they complete
            while in_flight:
                current_futures = set(in_flight.keys())
                done, _ = concurrent.futures.wait(
                    current_futures,
                    timeout=1.0,
                    return_when=concurrent.futures.FIRST_COMPLETED
                )

                for future in done:
                    try:
                        future.result()
                    except Exception as e:
                        import logging
                        logging.error(f"Future failed with exception: {e}")
                    del in_flight[future]

                # Submit more files to maintain queue
                submit_batch()

                # Exit if shutdown requested and no more in flight
                if self._shutdown_requested and not in_flight:
                    break

            # After all futures done, give UI one more refresh cycle
            import time
            time.sleep(1.5)
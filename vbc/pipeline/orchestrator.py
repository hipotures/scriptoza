import re
import threading
import concurrent.futures
import shutil
import logging
import time
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
from vbc.ui.keyboard import RequestShutdown, ThreadControlEvent, InterruptRequested

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
        self.logger = logging.getLogger(__name__)

        # Metadata cache (thread-safe)
        self._metadata_cache = {}  # Path -> VideoMetadata
        self._metadata_lock = threading.Lock()

        # Dynamic control state
        self._shutdown_requested = False
        self._current_max_threads = config.general.threads
        self._active_threads = 0
        self._thread_lock = threading.Condition()
        self._refresh_requested = False
        self._refresh_lock = threading.Lock()
        self._shutdown_event = threading.Event()  # Signal workers to stop

        self._setup_subscriptions()

    def _setup_subscriptions(self):
        from vbc.domain.events import RefreshRequested
        self.event_bus.subscribe(RequestShutdown, self._on_shutdown_request)
        self.event_bus.subscribe(ThreadControlEvent, self._on_thread_control)
        self.event_bus.subscribe(RefreshRequested, self._on_refresh_request)

    def _on_shutdown_request(self, event: RequestShutdown):
        with self._thread_lock:
            self._shutdown_requested = True
            self._thread_lock.notify_all()
        # Publish feedback message (like old vbc.py line 781)
        from vbc.domain.events import ActionMessage
        self.event_bus.publish(ActionMessage(message="SHUTDOWN requested"))

    def _on_thread_control(self, event: ThreadControlEvent):
        old_val = self._current_max_threads
        with self._thread_lock:
            new_val = self._current_max_threads + event.change
            self._current_max_threads = max(1, min(16, new_val))
            self._thread_lock.notify_all()
        # Publish feedback message (like old vbc.py lines 769, 776)
        from vbc.domain.events import ActionMessage
        if new_val != old_val:
            self.event_bus.publish(ActionMessage(message=f"Threads: {old_val} → {self._current_max_threads}"))

    def _on_refresh_request(self, event):
        with self._refresh_lock:
            self._refresh_requested = True

    def _get_metadata(self, video_file: VideoFile) -> Optional:
        """Get metadata with thread-safe caching (like get_queue_metadata in original)."""
        # Check if already cached
        with self._metadata_lock:
            cached = self._metadata_cache.get(video_file.path)
            if cached is not None:
                return cached

        # Not in cache, extract it
        try:
            if self.config.general.debug:
                self.logger.debug(f"Metadata cache miss: {video_file.path.name}")

            metadata = self.exif_adapter.extract_metadata(video_file)

            # Cache it
            with self._metadata_lock:
                self._metadata_cache[video_file.path] = metadata

            return metadata
        except Exception as e:
            self.logger.warning(f"Failed to extract metadata for {video_file.path.name}: {e}")
            return None

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

    def _perform_discovery(self, input_dir: Path) -> tuple:
        """Performs file discovery and returns (files_to_process, discovery_stats)."""
        if self.config.general.debug:
            self.logger.info(f"DISCOVERY_START: scanning {input_dir}")
        # First count all files (including small ones) for statistics
        import os
        total_files = 0
        ignored_small = 0
        for root, dirs, filenames in os.walk(str(input_dir)):
            root_path = Path(root)
            if root_path.name.endswith("_out"):
                dirs[:] = []
                continue
            for fname in filenames:
                fpath = root_path / fname
                if fpath.suffix.lower() in self.file_scanner.extensions:
                    total_files += 1
                    try:
                        if fpath.stat().st_size < self.file_scanner.min_size_bytes:
                            ignored_small += 1
                    except OSError:
                        pass

        # Now get files that pass size filter
        files = list(self.file_scanner.scan(input_dir))

        # Count files that will be skipped during discovery
        output_dir = input_dir.with_name(f"{input_dir.name}_out")
        already_compressed = 0
        ignored_err = 0
        files_to_process = []

        for vf in files:
            try:
                rel_path = vf.path.relative_to(input_dir)
            except ValueError:
                rel_path = vf.path.name
            # Always output as .mp4 (lowercase), regardless of input extension
            output_path = output_dir / rel_path.with_suffix('.mp4')
            err_path = output_path.with_suffix('.err')

            # Check for error markers FIRST (before timestamp check)
            if err_path.exists():
                if self.config.general.clean_errors:
                    err_path.unlink()  # Remove error marker
                else:
                    # Distinguish hw_cap errors from regular errors
                    try:
                        err_content = err_path.read_text()
                        if "Hardware is lacking required capabilities" in err_content:
                            pass  # hw_cap is not counted as ignored_err
                        else:
                            ignored_err += 1
                    except:
                        ignored_err += 1
                    continue

            # Check if already compressed
            if output_path.exists() and output_path.stat().st_mtime > vf.path.stat().st_mtime:
                already_compressed += 1
                continue

            # AV1 check is done during processing, not discovery
            files_to_process.append(vf)

        discovery_stats = {
            'files_found': total_files,
            'files_to_process': len(files_to_process),
            'already_compressed': already_compressed,
            'ignored_small': ignored_small,
            'ignored_err': ignored_err
        }

        if self.config.general.debug:
            self.logger.info(
                f"DISCOVERY_END: found={total_files}, to_process={len(files_to_process)}, "
                f"already_compressed={already_compressed}, ignored_small={ignored_small}, ignored_err={ignored_err}"
            )

        return files_to_process, discovery_stats

    def _process_file(self, video_file: VideoFile, input_dir: Path):
        """Processes a single file with dynamic concurrency control."""
        filename = video_file.path.name
        start_time = time.monotonic() if self.config.general.debug else None

        if self.config.general.debug:
            thread_id = threading.get_ident()
            self.logger.info(f"PROCESS_START: {filename} (thread {thread_id})")

        with self._thread_lock:
            while self._active_threads >= self._current_max_threads:
                self._thread_lock.wait()

            if self._shutdown_requested:
                if self.config.general.debug:
                    self.logger.info(f"PROCESS_SKIP: {filename} (shutdown)")
                return

            self._active_threads += 1

        try:
            # 1. Metadata & Decision (using thread-safe cache)
            video_file.metadata = self._get_metadata(video_file)
            
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
            # Always output as .mp4 (lowercase), regardless of input extension
            output_path = output_dir / rel_path.with_suffix('.mp4')
            output_path.parent.mkdir(parents=True, exist_ok=True)

            err_path = output_path.with_suffix('.err')
            
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
            self.ffmpeg_adapter.compress(job, job_config, rotate=rotation, shutdown_event=self._shutdown_event)

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
                if self.config.general.debug and start_time:
                    elapsed = time.monotonic() - start_time
                    self.logger.info(f"PROCESS_END: {filename} status=completed elapsed={elapsed:.2f}s")
            elif job.status == JobStatus.INTERRUPTED:
                # User pressed Ctrl+C - don't create .err, already cleaned up by FFmpegAdapter
                self.event_bus.publish(JobFailed(job=job, error_message=job.error_message))
                if self.config.general.debug and start_time:
                    elapsed = time.monotonic() - start_time
                    self.logger.info(f"PROCESS_END: {filename} status=interrupted elapsed={elapsed:.2f}s")
            elif job.status in (JobStatus.HW_CAP_LIMIT, JobStatus.FAILED):
                # Event already published by FFmpeg adapter, just write error marker
                with open(err_path, "w") as f:
                    f.write(job.error_message or "Unknown error")
                if self.config.general.debug and start_time:
                    elapsed = time.monotonic() - start_time
                    self.logger.info(f"PROCESS_END: {filename} status={job.status.value} elapsed={elapsed:.2f}s")
            elif job.status == JobStatus.PROCESSING:
                # Status not updated - treat as unknown error
                job.status = JobStatus.FAILED
                job.error_message = "Compression finished but status not updated"
                with open(err_path, "w") as f:
                    f.write(job.error_message)
                self.event_bus.publish(JobFailed(job=job, error_message=job.error_message))
                if self.config.general.debug and start_time:
                    elapsed = time.monotonic() - start_time
                    self.logger.info(f"PROCESS_END: {filename} status=failed reason=status_not_updated elapsed={elapsed:.2f}s")

        except KeyboardInterrupt:
            # Ctrl+C during processing - already handled by FFmpegAdapter if during ffmpeg
            # If happens elsewhere, set INTERRUPTED status
            if job.status == JobStatus.PROCESSING:
                job.status = JobStatus.INTERRUPTED
                job.error_message = "Interrupted by user (Ctrl+C)"
            self.event_bus.publish(JobFailed(job=job, error_message=job.error_message or "Interrupted"))
            if self.config.general.debug and start_time:
                elapsed = time.monotonic() - start_time
                self.logger.info(f"PROCESS_END: {filename} status=interrupted elapsed={elapsed:.2f}s")
            # Re-raise to propagate to main loop
            raise
        except Exception as e:
            # Log exception but don't crash the thread
            self.logger.error(f"Exception processing {filename}: {e}")
            job.status = JobStatus.FAILED
            job.error_message = f"Exception: {str(e)}"
            with open(err_path, "w") as f:
                f.write(job.error_message)
            self.event_bus.publish(JobFailed(job=job, error_message=job.error_message))
            if self.config.general.debug and start_time:
                elapsed = time.monotonic() - start_time
                self.logger.info(f"PROCESS_END: {filename} status=exception elapsed={elapsed:.2f}s")
        finally:
            with self._thread_lock:
                self._active_threads -= 1
                self._thread_lock.notify_all()

    def run(self, input_dir: Path):
        self.logger.info(f"Discovery started: {input_dir}")
        self.event_bus.publish(DiscoveryStarted(directory=input_dir))
        files_to_process, discovery_stats = self._perform_discovery(input_dir)

        self.logger.info(
            f"Discovery finished: found={discovery_stats['files_found']}, "
            f"to_process={discovery_stats['files_to_process']}, "
            f"already_compressed={discovery_stats['already_compressed']}, "
            f"ignored_err={discovery_stats['ignored_err']}"
        )

        self.event_bus.publish(DiscoveryFinished(
            files_found=discovery_stats['files_found'],
            files_to_process=discovery_stats['files_to_process'],
            already_compressed=discovery_stats['already_compressed'],
            ignored_small=discovery_stats['ignored_small'],
            ignored_err=discovery_stats['ignored_err'],
            ignored_av1=0  # AV1 check done during processing
        ))

        # If no files to process, exit early
        if len(files_to_process) == 0:
            self.logger.info("No files to process, exiting")
            return

        # Submit-on-demand pattern (like original vbc.py)
        from collections import deque
        pending = deque(files_to_process)
        in_flight = {}  # future -> VideoFile

        # Pre-load metadata for first 5 files (for queue display)
        for vf in list(pending)[:5]:
            if not vf.metadata:
                vf.metadata = self._get_metadata(vf)

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

                # Pre-load metadata for next 5 files in queue (for UI display)
                for vf in list(pending)[:5]:
                    if not vf.metadata:
                        vf.metadata = self._get_metadata(vf)

                # Update UI with current pending files (store VideoFile objects, not just paths)
                self.event_bus.publish(QueueUpdated(pending_files=[vf for vf in pending]))

            try:
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

                    # Check for refresh request
                    with self._refresh_lock:
                        if self._refresh_requested:
                            self._refresh_requested = False
                            # Perform new discovery
                            new_files, new_stats = self._perform_discovery(input_dir)
                            # Track already submitted files to avoid duplicates
                            submitted_paths = {vf.path for vf in in_flight.values()}
                            submitted_paths.update(vf.path for vf in pending)
                            # Add only new files not already in queue or processing
                            added = 0
                            for vf in new_files:
                                if vf.path not in submitted_paths:
                                    pending.append(vf)
                                    added += 1
                            # Update discovery stats (include ignored_small like old code)
                            self.event_bus.publish(DiscoveryFinished(
                                files_found=new_stats['files_found'],
                                files_to_process=new_stats['files_to_process'],
                                already_compressed=new_stats['already_compressed'],
                                ignored_small=new_stats['ignored_small'],  # FIX: update this counter
                                ignored_err=new_stats['ignored_err'],
                                ignored_av1=0  # AV1 check done during processing
                            ))
                            # Publish feedback message (like old vbc.py lines 1852-1860)
                            from vbc.domain.events import ActionMessage
                            if added > 0:
                                self.event_bus.publish(ActionMessage(message=f"Refreshed: +{added} new files"))
                                self.logger.info(f"Refresh: added {added} new files to queue")
                            else:
                                self.event_bus.publish(ActionMessage(message="Refreshed: no changes"))
                                self.logger.info("Refresh: no changes detected")

                    # Submit more files to maintain queue
                    submit_batch()

                    # Exit if shutdown requested and no more in flight
                    if self._shutdown_requested and not in_flight:
                        self.logger.info("Shutdown requested, exiting processing loop")
                        break

                # After all futures done, give UI one more refresh cycle
                time.sleep(1.5)
                self.logger.info("All files processed, exiting")

            except KeyboardInterrupt:
                # User pressed Ctrl+C - graceful shutdown like old vbc.py (lines 1980-1997)
                self.logger.info("Ctrl+C detected - stopping new tasks and interrupting active jobs...")
                from vbc.domain.events import ActionMessage
                self.event_bus.publish(InterruptRequested())
                self.event_bus.publish(ActionMessage(message="Ctrl+C - interrupting active compressions..."))

                # Signal all workers to stop immediately
                self._shutdown_event.set()

                # Stop accepting new tasks
                self._shutdown_requested = True

                # Cancel all pending futures (not yet started)
                for future in list(in_flight.keys()):
                    if not future.done():
                        future.cancel()

                # Wait for currently running tasks to see shutdown_event (max 10 seconds)
                self.logger.info("Waiting for active ffmpeg processes to terminate (max 10s)...")
                deadline = time.monotonic() + 10.0
                while True:
                    running = [future for future in in_flight if not future.done()]
                    if not running:
                        break
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        break
                    concurrent.futures.wait(
                        running,
                        timeout=min(0.2, remaining),
                        return_when=concurrent.futures.FIRST_COMPLETED
                    )

                # Force shutdown after timeout
                executor.shutdown(wait=False, cancel_futures=True)
                self.logger.info("Shutdown complete")

                # Re-raise to propagate to main
                raise

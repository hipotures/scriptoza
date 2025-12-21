from vbc.infrastructure.event_bus import EventBus
from vbc.ui.state import UIState
from vbc.domain.events import (
    DiscoveryStarted, DiscoveryFinished,
    JobStarted, JobCompleted, JobFailed,
    JobProgressUpdated, HardwareCapabilityExceeded, QueueUpdated,
    ActionMessage
)
from vbc.ui.keyboard import ThreadControlEvent, RequestShutdown

class UIManager:
    """Subscribes to EventBus and updates UIState."""
    
    def __init__(self, bus: EventBus, state: UIState):
        self.bus = bus
        self.state = state
        self._setup_subscriptions()

    def _setup_subscriptions(self):
        self.bus.subscribe(DiscoveryStarted, self.on_discovery_started)
        self.bus.subscribe(DiscoveryFinished, self.on_discovery_finished)
        self.bus.subscribe(JobStarted, self.on_job_started)
        self.bus.subscribe(JobCompleted, self.on_job_completed)
        self.bus.subscribe(JobFailed, self.on_job_failed)
        self.bus.subscribe(JobProgressUpdated, self.on_job_progress)
        self.bus.subscribe(HardwareCapabilityExceeded, self.on_hw_cap_exceeded)
        self.bus.subscribe(ThreadControlEvent, self.on_thread_control)
        self.bus.subscribe(RequestShutdown, self.on_shutdown_request)
        self.bus.subscribe(QueueUpdated, self.on_queue_updated)
        self.bus.subscribe(ActionMessage, self.on_action_message)

    def on_discovery_started(self, event: DiscoveryStarted):
        self.state.discovery_finished = False

    def on_discovery_finished(self, event: DiscoveryFinished):
        # Debug: log when discovery counters are updated
        import logging
        logger = logging.getLogger(__name__)
        logger.debug(
            f"UI: Updating discovery counters: to_process={event.files_to_process}, "
            f"already_compressed={event.already_compressed}, ignored_small={event.ignored_small}, "
            f"ignored_err={event.ignored_err}"
        )

        self.state.total_files_found = event.files_found
        self.state.files_to_process = event.files_to_process
        self.state.already_compressed_count = event.already_compressed
        self.state.ignored_small_count = event.ignored_small
        self.state.ignored_err_count = event.ignored_err
        self.state.ignored_av1_count = event.ignored_av1
        self.state.discovery_finished = True

    def on_thread_control(self, event: ThreadControlEvent):
        with self.state._lock:
            new_val = self.state.current_threads + event.change
            self.state.current_threads = max(1, min(16, new_val))

    def on_shutdown_request(self, event: RequestShutdown):
        with self.state._lock:
            self.state.shutdown_requested = True

    def on_job_started(self, event: JobStarted):
        # Track when first job starts
        from datetime import datetime
        if self.state.processing_start_time is None:
            self.state.processing_start_time = datetime.now()
        self.state.add_active_job(event.job)

    def on_job_completed(self, event: JobCompleted):
        output_size = 0
        if event.job.output_path and event.job.output_path.exists():
            output_size = event.job.output_path.stat().st_size

        # Calculate duration
        from datetime import datetime
        filename = event.job.source_file.path.name
        if filename in self.state.job_start_times:
            start_time = self.state.job_start_times[filename]
            event.job.duration_seconds = (datetime.now() - start_time).total_seconds()

        # Check if this is a min_ratio_skip (original file kept)
        if event.job.error_message and "kept original" in event.job.error_message:
            with self.state._lock:
                self.state.min_ratio_skip_count += 1

        self.state.add_completed_job(event.job, output_size)

    def on_job_failed(self, event: JobFailed):
        # Calculate duration
        from datetime import datetime
        from vbc.domain.models import JobStatus
        filename = event.job.source_file.path.name
        if filename in self.state.job_start_times:
            start_time = self.state.job_start_times[filename]
            event.job.duration_seconds = (datetime.now() - start_time).total_seconds()

        # Check if it's an AV1 skip
        if event.error_message and "Already encoded in AV1" in event.error_message:
            with self.state._lock:
                self.state.ignored_av1_count += 1
            # Don't add to failed jobs - just increment counter
            self.state.remove_active_job(event.job)
        # Check if it's INTERRUPTED (Ctrl+C)
        elif event.job.status == JobStatus.INTERRUPTED:
            with self.state._lock:
                self.state.interrupted_count += 1
            # Add to recent jobs to show in LAST COMPLETED
            self.state.recent_jobs.appendleft(event.job)
            self.state.remove_active_job(event.job)
        else:
            self.state.add_failed_job(event.job)

    def on_hw_cap_exceeded(self, event: HardwareCapabilityExceeded):
        self.state.hw_cap_count += 1
        # Don't add to recent_jobs - hw_cap is only counted, not shown in LAST COMPLETED
        self.state.remove_active_job(event.job)

    def on_job_progress(self, event: JobProgressUpdated):
        pass

    def on_queue_updated(self, event: QueueUpdated):
        with self.state._lock:
            # Store VideoFile objects (not just paths) to preserve metadata
            self.state.pending_files = list(event.pending_files)

    def on_action_message(self, event: ActionMessage):
        """Handle user action feedback messages (like old vbc.py)."""
        self.state.set_last_action(event.message)

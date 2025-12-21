import os
from vbc.infrastructure.event_bus import EventBus
from vbc.ui.state import UIState
from vbc.domain.events import (
    DiscoveryStarted, DiscoveryFinished, 
    JobStarted, JobCompleted, JobFailed, 
    JobProgressUpdated, HardwareCapabilityExceeded
)

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

    def on_discovery_started(self, event: DiscoveryStarted):
        self.state.discovery_finished = False

    def on_discovery_finished(self, event: DiscoveryFinished):
        self.state.total_files_found = event.files_found
        self.state.discovery_finished = True

    def on_job_started(self, event: JobStarted):
        self.state.add_active_job(event.job)

    def on_job_completed(self, event: JobCompleted):
        # Determine output size for stats
        output_size = 0
        if event.job.output_path and event.job.output_path.exists():
            output_size = event.job.output_path.stat().st_size
        
        self.state.add_completed_job(event.job, output_size)

    def on_job_failed(self, event: JobFailed):
        self.state.add_failed_job(event.job)

    def on_hw_cap_exceeded(self, event: HardwareCapabilityExceeded):
        self.state.hw_cap_count += 1
        self.state.remove_active_job(event.job)

    def on_job_progress(self, event: JobProgressUpdated):
        # Progress logic if needed (state currently tracks active jobs which have progress info)
        pass

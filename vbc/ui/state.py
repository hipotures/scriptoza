import threading
from collections import deque
from typing import List, Optional
from vbc.domain.models import CompressionJob

class UIState:
    """Thread-safe state manager for the interactive UI."""
    
    def __init__(self):
        self._lock = threading.RLock()
        
        # Counters
        self.completed_count = 0
        self.failed_count = 0
        self.skipped_count = 0
        self.hw_cap_count = 0
        self.cam_skipped_count = 0
        
        # Bytes tracking
        self.total_input_bytes = 0
        self.total_output_bytes = 0
        
        # Job lists
        self.active_jobs: List[CompressionJob] = []
        self.recent_jobs = deque(maxlen=5)
        
        # Global Status
        self.discovery_finished = False
        self.total_files_found = 0
        self.current_threads = 0
        self.shutdown_requested = False

    @property
    def space_saved_bytes(self) -> int:
        with self._lock:
            return max(0, self.total_input_bytes - self.total_output_bytes)

    @property
    def compression_ratio(self) -> float:
        with self._lock:
            if self.total_input_bytes == 0:
                return 0.0
            return self.total_output_bytes / self.total_input_bytes

    def add_active_job(self, job: CompressionJob):
        with self._lock:
            if job not in self.active_jobs:
                self.active_jobs.append(job)

    def remove_active_job(self, job: CompressionJob):
        with self._lock:
            if job in self.active_jobs:
                self.active_jobs.remove(job)

    def add_completed_job(self, job: CompressionJob, output_size: int):
        with self._lock:
            self.completed_count += 1
            self.total_input_bytes += job.source_file.size_bytes
            self.total_output_bytes += output_size
            self.recent_jobs.appendleft(job)
            self.remove_active_job(job)

    def add_failed_job(self, job: CompressionJob):
        with self._lock:
            self.failed_count += 1
            self.recent_jobs.appendleft(job)
            self.remove_active_job(job)

    def add_skipped_job(self, job: CompressionJob):
        with self._lock:
            self.skipped_count += 1
            self.remove_active_job(job)

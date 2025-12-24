import json
import subprocess
import threading
import time
import logging
from typing import Optional, Dict, Any
from vbc.ui.state import UIState

class GpuMonitor:
    """Monitors GPU metrics using nvtop -s in a background thread."""
    
    def __init__(self, state: UIState, refresh_rate: int = 5):
        self.state = state
        self.refresh_rate = refresh_rate
        self.logger = logging.getLogger(__name__)
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def _poll(self):
        """Polls nvtop and updates state."""
        while not self._stop_event.is_set():
            try:
                # nvtop -s produces a JSON list of GPUs
                result = subprocess.run(
                    ["nvtop", "-s"],
                    capture_output=True,
                    text=True,
                    check=True
                )
                if result.stdout:
                    data = json.loads(result.stdout)
                    if isinstance(data, list) and len(data) > 0:
                        with self.state._lock:
                            self.state.gpu_data = data[0] # Monitor first GPU
            except (subprocess.CalledProcessError, json.JSONDecodeError, FileNotFoundError) as e:
                self.logger.debug(f"GPU Monitor: failed to fetch data: {e}")
                with self.state._lock:
                    self.state.gpu_data = None
            
            # Wait for refresh rate or stop event
            self._stop_event.wait(self.refresh_rate)

    def start(self):
        """Starts the monitoring thread."""
        if self._thread is not None:
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._poll, daemon=True)
        self._thread.start()
        self.logger.info("GPU Monitor started")

    def stop(self):
        """Stops the monitoring thread."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=1.0)
            self._thread = None
        self.logger.info("GPU Monitor stopped")

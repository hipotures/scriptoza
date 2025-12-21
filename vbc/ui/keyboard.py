import sys
import threading
import termios
import tty
import select
from typing import Optional
from vbc.infrastructure.event_bus import EventBus
from vbc.domain.events import Event

class RequestShutdown(Event):
    """Event emitted when user requests graceful shutdown (Key 'S')."""
    pass

class ThreadControlEvent(Event):
    """Event emitted to adjust thread count (Keys '<' or '>')."""
    change: int # +1 or -1

class KeyboardListener:
    """Listens for keyboard input in a background thread."""
    
    def __init__(self, event_bus: EventBus):
        self.event_bus = event_bus
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def _get_key(self) -> Optional[str]:
        """Reads a single key from stdin in raw mode."""
        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)
        try:
            tty.setraw(sys.stdin.fileno())
            rlist, _, _ = select.select([sys.stdin], [], [], 0.1)
            if rlist:
                return sys.stdin.read(1)
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
        return None

    def _run(self):
        """Main loop for the listener thread."""
        while not self._stop_event.is_set():
            key = self._get_key()
            if key:
                key = key.upper()
                if key == 'S':
                    self.event_bus.publish(RequestShutdown())
                elif key in ('.', '>'):
                    self.event_bus.publish(ThreadControlEvent(change=1))
                elif key in (',', '<'):
                    self.event_bus.publish(ThreadControlEvent(change=-1))
                elif key == '\x03': # Ctrl+C
                    self.event_bus.publish(RequestShutdown())
                    break

    def start(self):
        """Starts the listener thread."""
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        """Stops the listener thread."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=1.0)

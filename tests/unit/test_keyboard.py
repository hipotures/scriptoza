import pytest
from unittest.mock import MagicMock
from vbc.ui.keyboard import KeyboardListener, RequestShutdown, ThreadControlEvent, ToggleConfig
from vbc.infrastructure.event_bus import EventBus

def test_keyboard_listener_initialization():
    """Test that KeyboardListener can be initialized with EventBus."""
    bus = EventBus()
    listener = KeyboardListener(bus)
    assert listener.event_bus is bus
    assert listener._stop_event is not None

def test_keyboard_listener_stop_event():
    """Test that listener has a stop event for thread control."""
    bus = EventBus()
    listener = KeyboardListener(bus)
    assert not listener._stop_event.is_set()

    # Calling stop() should set the event
    listener.stop()
    assert listener._stop_event.is_set()

def test_request_shutdown_event():
    """Test RequestShutdown event can be created."""
    event = RequestShutdown()
    assert event is not None

def test_thread_control_event():
    """Test ThreadControlEvent with change values."""
    increase_event = ThreadControlEvent(change=1)
    decrease_event = ThreadControlEvent(change=-1)

    assert increase_event.change == 1
    assert decrease_event.change == -1

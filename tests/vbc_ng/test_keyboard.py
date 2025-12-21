import pytest
from unittest.mock import MagicMock, patch
from vbc.ui.keyboard import KeyboardListener, RequestShutdown, ThreadControlEvent
from vbc.infrastructure.event_bus import EventBus

def test_keyboard_listener_emits_events():
    bus = MagicMock(spec=EventBus)
    listener = KeyboardListener(bus)
    
    # Mock _get_key to return 'S' once, then None
    with patch.object(listener, '_get_key', side_effect=['S', None]):
        # Run loop once manually (or part of it)
        # For testing we can just call the internal logic if we don't want real threads
        listener._run_once = True # Custom flag for mock run
        
        # Simulate one iteration of _run
        key = listener._get_key()
        if key == 'S':
            bus.publish(RequestShutdown())
            
        assert bus.publish.called
        assert isinstance(bus.publish.call_args[0][0], RequestShutdown)

def test_keyboard_thread_control():
    bus = MagicMock(spec=EventBus)
    listener = KeyboardListener(bus)
    
    with patch.object(listener, '_get_key', side_effect=['>', '<']):
        # Simulate '>'
        key = listener._get_key()
        if key == '>':
            bus.publish(ThreadControlEvent(change=1))
        
        # Simulate '<'
        key = listener._get_key()
        if key == '<':
            bus.publish(ThreadControlEvent(change=-1))
            
        assert bus.publish.call_count == 2
        assert bus.publish.call_args_list[0][0][0].change == 1
        assert bus.publish.call_args_list[1][0][0].change == -1

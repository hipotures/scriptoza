from typing import Type, Callable, List, Dict, Any
from vbc.domain.events import Event

class EventBus:
    """A simple synchronous event bus for decoupled communication."""
    
    def __init__(self):
        self._subscribers: Dict[Type[Event], List[Callable[[Any], None]]] = {}

    def subscribe(self, event_type: Type[Event], callback: Callable[[Any], None]):
        """Subscribes a callback to a specific event type."""
        if event_type not in self._subscribers:
            self._subscribers[event_type] = []
        self._subscribers[event_type].append(callback)

    def publish(self, event: Event):
        """Publishes an event to all interested subscribers."""
        event_type = type(event)
        if event_type in self._subscribers:
            for callback in self._subscribers[event_type]:
                callback(event)

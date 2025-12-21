import pytest
from vbc.ui.state import UIState
from vbc.ui.dashboard import Dashboard

def test_dashboard_initialization():
    """Test that Dashboard can be initialized with UIState."""
    state = UIState()
    dashboard = Dashboard(state)
    assert dashboard.state is state

def test_dashboard_context_manager():
    """Test that Dashboard can be used as context manager."""
    state = UIState()
    dashboard = Dashboard(state)
    # Dashboard should have __enter__ and __exit__ for context manager protocol
    assert hasattr(dashboard, '__enter__')
    assert hasattr(dashboard, '__exit__')

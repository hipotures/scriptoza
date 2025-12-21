import pytest
from vbc.ui.state import UIState
from vbc.ui.dashboard import Dashboard
from rich.layout import Layout

def test_dashboard_layout_generation():
    state = UIState()
    dashboard = Dashboard(state)
    layout = dashboard.make_layout()
    assert isinstance(layout, Layout)
    # Check if panels are present in layout names
    assert layout.get("header") is not None
    assert layout.get("main") is not None
    assert layout.get("footer") is not None

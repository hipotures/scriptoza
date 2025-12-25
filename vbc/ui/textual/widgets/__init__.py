"""Widget components for Textual dashboard."""

from vbc.ui.textual.widgets.header import HeaderWidget
from vbc.ui.textual.widgets.progress_panel import ProgressPanel
from vbc.ui.textual.widgets.active_jobs import ActiveJobsPanel
from vbc.ui.textual.widgets.activity_feed import ActivityFeed
from vbc.ui.textual.widgets.queue_panel import QueuePanel
from vbc.ui.textual.widgets.gpu_sparkline import GPUSparkline
from vbc.ui.textual.widgets.health_footer import HealthFooter

__all__ = [
    "HeaderWidget",
    "ProgressPanel",
    "ActiveJobsPanel",
    "ActivityFeed",
    "QueuePanel",
    "GPUSparkline",
    "HealthFooter",
]

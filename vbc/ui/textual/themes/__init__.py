"""Theme management for Textual dashboard."""

from pathlib import Path

THEMES_DIR = Path(__file__).parent

AVAILABLE_THEMES = ["cyberpunk", "minimalist", "retro", "material"]

DEFAULT_THEME = "cyberpunk"


def get_theme_path(theme_name: str) -> Path:
    """Get the path to a theme CSS file."""
    if theme_name not in AVAILABLE_THEMES:
        theme_name = DEFAULT_THEME
    return THEMES_DIR / f"{theme_name}.tcss"


def get_all_theme_paths() -> list[Path]:
    """Get paths to all theme CSS files."""
    return [THEMES_DIR / f"{name}.tcss" for name in AVAILABLE_THEMES]

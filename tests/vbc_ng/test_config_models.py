import pytest
from pydantic import ValidationError
from scriptoza.vbc.config.models import AppConfig, GeneralConfig, AutoRotateConfig

def test_valid_config():
    data = {
        "general": {
            "threads": 4,
            "cq": 45,
            "gpu": True,
            "copy_metadata": True,
            "use_exif": True,
            "filter_cameras": ["Sony"],
            "dynamic_cq": {"Sony": 35},
            "extensions": [".mp4"],
            "min_size_bytes": 1024
        },
        "autorotate": {
            "patterns": {"QVR.*": 180}
        }
    }
    config = AppConfig(**data)
    assert config.general.threads == 4
    assert config.autorotate.patterns["QVR.*"] == 180

def test_invalid_threads():
    with pytest.raises(ValidationError):
        GeneralConfig(threads=0, cq=45, gpu=True, copy_metadata=True, use_exif=True, extensions=[".mp4"], min_size_bytes=0)

def test_invalid_cq():
    with pytest.raises(ValidationError):
        GeneralConfig(threads=4, cq=64, gpu=True, copy_metadata=True, use_exif=True, extensions=[".mp4"], min_size_bytes=0)

def test_config_defaults():
    # Test minimal required fields if any (assuming some defaults exist)
    gen = GeneralConfig(threads=1, cq=45, gpu=True, copy_metadata=True, use_exif=True, extensions=[".mp4"], min_size_bytes=0)
    assert gen.filter_cameras == []
    assert gen.dynamic_cq == {}

def test_load_config(tmp_path):
    d = tmp_path / "conf"
    d.mkdir()
    f = d / "vbc.yaml"
    f.write_text("""
general:
  threads: 8
  cq: 30
autorotate:
  patterns:
    "test.*": 90
""")
    from scriptoza.vbc.config.loader import load_config
    config = load_config(f)
    assert config.general.threads == 8
    assert config.general.cq == 30
    assert config.autorotate.patterns["test.*"] == 90

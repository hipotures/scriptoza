import pytest
import json
from pathlib import Path
from unittest.mock import patch, MagicMock
from vbc.infrastructure.ffprobe import FFprobeAdapter

def test_ffprobe_parse_streams():
    mock_output = {
        "streams": [
            {
                "index": 0,
                "codec_name": "h264",
                "codec_type": "video",
                "width": 1920,
                "height": 1080,
                "r_frame_rate": "30/1",
                "avg_frame_rate": "30/1",
                "bit_rate": "5000000"
            }
        ],
        "format": {
            "duration": "10.0"
        }
    }
    
    with patch("subprocess.run") as mock_run:
        mock_run.return_value.stdout = json.dumps(mock_output)
        mock_run.return_value.returncode = 0
        
        adapter = FFprobeAdapter()
        info = adapter.get_stream_info(Path("test.mp4"))
        
        assert info["width"] == 1920
        assert info["height"] == 1080
        assert info["codec"] == "h264"
        assert info["fps"] == 30.0
        assert info["duration"] == 10.0

def test_ffprobe_error():
    with patch("subprocess.run") as mock_run:
        mock_run.return_value.returncode = 1
        mock_run.return_value.stderr = "error"
        
        adapter = FFprobeAdapter()
        with pytest.raises(RuntimeError):
            adapter.get_stream_info(Path("test.mp4"))

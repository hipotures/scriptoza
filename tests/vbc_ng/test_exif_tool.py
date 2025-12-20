import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from vbc.infrastructure.exif_tool import ExifToolAdapter
from vbc.domain.models import VideoFile

def test_extract_metadata():
    mock_exif_data = [{
        "SourceFile": "test.mp4",
        "QuickTime:ImageWidth": 1920,
        "QuickTime:ImageHeight": 1080,
        "QuickTime:VideoFrameRate": 60,
        "QuickTime:HandlerDescription": "VideoHandler",
        "QuickTime:Model": "DJI Osmo Pocket 3",
        "QuickTime:AvgBitrate": 100000000
    }]
    
    with patch("exiftool.ExifTool") as MockExifTool:
        instance = MockExifTool.return_value
        instance.get_metadata_batch.return_value = mock_exif_data
        
        adapter = ExifToolAdapter()
        vf = VideoFile(path=Path("test.mp4"), size_bytes=1000)
        metadata = adapter.extract_metadata(vf)
        
        assert metadata.width == 1920
        assert metadata.height == 1080
        assert metadata.fps == 60
        assert metadata.camera_model == "DJI Osmo Pocket 3"

def test_copy_metadata():
    with patch("exiftool.ExifTool") as MockExifTool:
        instance = MockExifTool.return_value
        adapter = ExifToolAdapter()
        
        adapter.copy_metadata(Path("src.mp4"), Path("dest.mp4"))
        
        # Verify exiftool was called with correct arguments for copying
        instance.execute.assert_called()
        args = instance.execute.call_args[0]
        assert "-tagsFromFile" in args
        assert "src.mp4" in args
        assert "dest.mp4" in args

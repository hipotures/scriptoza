import exiftool
from pathlib import Path
from typing import Optional, List, Dict, Any
from vbc.domain.models import VideoFile, VideoMetadata

class ExifToolAdapter:
    """Wrapper around pyexiftool for metadata extraction and manipulation."""
    
    def __init__(self):
        self.et = exiftool.ExifTool()

    def _get_tag(self, data: Dict[str, Any], tags: List[str]) -> Optional[Any]:
        """Tries to find the first available tag from a list of aliases."""
        for tag in tags:
            if tag in data:
                return data[tag]
        return None

    def extract_metadata(self, file: VideoFile) -> VideoMetadata:
        """Extracts metadata from a video file using ExifTool."""
        if not self.et.running:
            self.et.run()
            
        metadata_list = self.et.execute_json(str(file.path))
        if not metadata_list:
            raise ValueError(f"Could not extract metadata for {file.path}")
            
        data = metadata_list[0]
        
        width = self._get_tag(data, ["QuickTime:ImageWidth", "Track1:ImageWidth", "ImageWidth"])
        height = self._get_tag(data, ["QuickTime:ImageHeight", "Track1:ImageHeight", "ImageHeight"])
        fps = self._get_tag(data, ["QuickTime:VideoFrameRate", "VideoFrameRate"])
        # Get video codec ID (avc1=h264, hvc1=hevc, etc), not HandlerDescription which can be "Sound"
        codec_raw = self._get_tag(data, ["QuickTime:CompressorID", "CompressorID", "VideoCodec", "CompressorName"])

        # Map codec IDs to user-friendly names
        codec_map = {
            "avc1": "h264",
            "hvc1": "hevc",
            "hev1": "hevc",
            "av01": "av1",
            "vp09": "vp9",
            "vp08": "vp8"
        }
        codec = codec_map.get(str(codec_raw).lower(), str(codec_raw)) if codec_raw else "unknown"

        camera = self._get_tag(data, ["QuickTime:Model", "Model", "CameraModelName"])
        bitrate = self._get_tag(data, ["QuickTime:AvgBitrate", "AvgBitrate"])

        return VideoMetadata(
            width=int(width) if width else 0,
            height=int(height) if height else 0,
            codec=codec,
            fps=float(fps) if fps else 0.0,
            camera_model=str(camera) if camera else None,
            bitrate_kbps=float(bitrate) / 1000 if bitrate else None
        )

    def copy_metadata(self, source: Path, target: Path):
        """Copies EXIF/XMP tags from source to target."""
        if not self.et.running:
            self.et.run()
            
        # Standard command for deep EXIF/XMP copy
        cmd = [
            "-tagsFromFile", str(source),
            "-all:all",
            "-unsafe",
            "-overwrite_original",
            str(target)
        ]
        self.et.execute(*cmd)

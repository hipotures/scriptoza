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
            self.et.start()
            
        metadata_list = self.et.get_metadata_batch([str(file.path)])
        if not metadata_list:
            raise ValueError(f"Could not extract metadata for {file.path}")
            
        data = metadata_list[0]
        
        width = self._get_tag(data, ["QuickTime:ImageWidth", "Track1:ImageWidth", "ImageWidth"])
        height = self._get_tag(data, ["QuickTime:ImageHeight", "Track1:ImageHeight", "ImageHeight"])
        fps = self._get_tag(data, ["QuickTime:VideoFrameRate", "VideoFrameRate"])
        codec = self._get_tag(data, ["QuickTime:HandlerDescription", "CompressorName"])
        camera = self._get_tag(data, ["QuickTime:Model", "Model", "CameraModelName"])
        bitrate = self._get_tag(data, ["QuickTime:AvgBitrate", "AvgBitrate"])
        
        return VideoMetadata(
            width=int(width) if width else 0,
            height=int(height) if height else 0,
            codec=str(codec) if codec else "unknown",
            fps=float(fps) if fps else 0.0,
            camera_model=str(camera) if camera else None,
            bitrate_kbps=float(bitrate) / 1000 if bitrate else None
        )

    def copy_metadata(self, source: Path, target: Path):
        """Copies EXIF/XMP tags from source to target."""
        if not self.et.running:
            self.et.start()
            
        # Standard command for deep EXIF/XMP copy
        cmd = [
            "-tagsFromFile", str(source),
            "-all:all",
            "-unsafe",
            "-overwrite_original",
            str(target)
        ]
        self.et.execute(*cmd)

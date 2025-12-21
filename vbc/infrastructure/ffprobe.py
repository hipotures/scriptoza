import subprocess
import json
from pathlib import Path
from typing import Dict, Any, Optional

class FFprobeAdapter:
    """Wrapper around ffprobe to extract stream information."""
    
    def get_stream_info(self, file_path: Path) -> Dict[str, Any]:
        """Executes ffprobe and parses JSON output."""
        cmd = [
            "ffprobe",
            "-v", "quiet",
            "-print_format", "json",
            "-show_streams",
            "-show_format",
            str(file_path)
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"ffprobe failed for {file_path}: {result.stderr}")
            
        data = json.loads(result.stdout)
        
        # Find video stream
        video_stream = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), None)
        if not video_stream:
            raise ValueError(f"No video stream found in {file_path}")
            
        # Parse FPS (prefer avg_frame_rate; r_frame_rate is often timebase)
        fps = 0.0
        fps_str = video_stream.get("avg_frame_rate", "0/0")
        if "/" in fps_str:
            try:
                num, den = map(float, fps_str.split("/"))
                if den != 0:
                    candidate = num / den
                    if candidate <= 240:
                        fps = round(candidate)
            except ValueError:
                fps = 0.0
        else:
            try:
                candidate = float(fps_str)
                if candidate <= 240:
                    fps = round(candidate)
            except ValueError:
                fps = 0.0

        return {
            "width": int(video_stream.get("width", 0)),
            "height": int(video_stream.get("height", 0)),
            "codec": video_stream.get("codec_name", "unknown"),
            "fps": fps,
            "duration": float(data.get("format", {}).get("duration", 0.0)),
            "color_space": video_stream.get("color_space"),
        }

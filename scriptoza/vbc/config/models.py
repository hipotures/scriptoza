from typing import List, Dict, Optional
from pydantic import BaseModel, Field, field_validator

class GeneralConfig(BaseModel):
    threads: int = Field(gt=0)
    cq: int = Field(ge=0, le=63)
    gpu: bool = True
    copy_metadata: bool = True
    use_exif: bool = True
    filter_cameras: List[str] = Field(default_factory=list)
    dynamic_cq: Dict[str, int] = Field(default_factory=dict)
    extensions: List[str] = Field(default_factory=lambda: [".mp4", ".mov", ".avi"])
    min_size_bytes: int = Field(default=1048576) # 1 MiB

class AutoRotateConfig(BaseModel):
    patterns: Dict[str, int] = Field(default_factory=dict)

    @field_validator('patterns')
    @classmethod
    def validate_angles(cls, v: Dict[str, int]) -> Dict[str, int]:
        for pattern, angle in v.items():
            if angle not in {0, 90, 180, 270}:
                raise ValueError(f"Invalid rotation angle {angle} for pattern {pattern}. Must be 0, 90, 180, or 270.")
        return v

class AppConfig(BaseModel):
    general: GeneralConfig
    autorotate: AutoRotateConfig = Field(default_factory=AutoRotateConfig)

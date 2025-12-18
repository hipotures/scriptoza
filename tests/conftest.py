import pytest
import subprocess
import os
import shutil
import yaml
from pathlib import Path

@pytest.fixture
def test_data_dir(tmp_path):
    """Przygotowuje katalog testowy na bazie rzeczywistych wycinków 10s"""
    d = tmp_path / "input"
    d.mkdir()
    
    data_src = Path(__file__).resolve().parent / "data"
    
    # 1. Sony
    sony_file = d / "sony_test.mp4"
    shutil.copy(data_src / "sony_10s.mp4", sony_file)
    # Wymuszamy model w wielu polach, żeby vbc go na pewno znalazło
    subprocess.run(["exiftool", "-Model=ILCE-7RM5", "-Sony:DeviceModelName=ILCE-7RM5", "-overwrite_original", str(sony_file)], capture_output=True)

    # 2. GH7
    gh7_file = d / "gh7_test.mp4"
    shutil.copy(data_src / "gh7_10s.mp4", gh7_file)
    subprocess.run(["exiftool", "-Model=DC-GH7", "-Make=Panasonic", "-Panasonic:Make=Panasonic", "-GPSLatitude=50.0615", "-overwrite_original", str(gh7_file)], capture_output=True)

    # 3. DJI
    dji_file = d / "dji_test.mp4"
    shutil.copy(data_src / "dji_10s.mp4", dji_file)
    subprocess.run(["exiftool", "-Model=DJI OsmoPocket3", "-Make=DJI", "-DJI:Make=DJI", "-overwrite_original", str(dji_file)], capture_output=True)

    # 4. QVR (używamy DJI jako bazy)
    shutil.copy(data_src / "dji_10s.mp4", d / "QVR_20250101_120000.mp4")

    return d

@pytest.fixture
def vbc_yaml(tmp_path):
    conf_dir = tmp_path / "conf"
    conf_dir.mkdir()
    conf_file = conf_dir / "vbc.yaml"
    
    content = {
        'general': {
            'threads': 2,
            'cq': 45,
            'gpu': False, # Używamy CPU w testach dla przewidywalności rozmiarów
            'copy_metadata': True,
            'extensions': ['mp4', 'mov'],
            'min_size_bytes': 0,
            'use_exif': True,
            'dynamic_cq': {
                'DC-GH7': 30,
                'ILCE-7RM5': 35,
                'DJI OsmoPocket3': 35
            },
            'filter_cameras': []
        },
        'autorotate': {
            'QVR_\\d{8}_\\d{6}\\.mp4': 180
        }
    }
    
    with open(conf_file, 'w') as f:
        yaml.dump(content, f)
    
    return conf_file

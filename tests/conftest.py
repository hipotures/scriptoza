import pytest
import subprocess
import os
import shutil
import yaml
from pathlib import Path

@pytest.fixture
def test_data_dir(tmp_path):
    """Przygotowuje katalog testowy na bazie rzeczywistych wycinków 10s z Twoich aparatów"""
    d = tmp_path / "input"
    d.mkdir()
    
    # Katalog z wycinkami, które stworzyliśmy wcześniej z Twoich plików /tmp/
    data_src = Path(__file__).resolve().parent / "data"
    
    files = {
        "sony_test.mp4": data_src / "sony_10s.mp4",
        "gh7_test.mp4": data_src / "gh7_10s.mp4",
        "dji_test.mp4": data_src / "dji_10s.mp4"
    }
    
    for target_name, src_path in files.items():
        if src_path.exists():
            shutil.copy(src_path, d / target_name)
        else:
            pytest.skip(f"Brak pliku wzorcowego: {src_path}. Upewnij się, że wycinki 10s istnieją.")

    # Wymuszamy stabilne metadane dla testów (model, producent, GPS).
    metadata_updates = {
        "sony_test.mp4": [
            "-Model=ILCE-7RM5",
            "-Sony:DeviceModelName=ILCE-7RM5",
            "-Make=Sony",
        ],
        "gh7_test.mp4": [
            "-Model=DC-GH7",
            "-Make=Panasonic",
            "-Panasonic:Make=Panasonic",
            "-GPSLatitude=50.0615",
            "-GPSLongitude=19.9380",
        ],
        "dji_test.mp4": [
            "-Model=DJI OsmoPocket3",
            "-Make=DJI",
            "-DJI:Make=DJI",
        ],
    }

    for filename, tags in metadata_updates.items():
        file_path = d / filename
        if file_path.exists():
            subprocess.run(
                ["exiftool", *tags, "-overwrite_original", str(file_path)],
                capture_output=True
            )

    # Plik QVR do testu rotacji (używamy DJI jako bazy nazwy)
    shutil.copy(data_src / "dji_10s.mp4", d / "QVR_20250101_120000.mp4")

    return d

@pytest.fixture
def vbc_yaml(tmp_path):
    conf_dir = tmp_path / "conf"
    conf_dir.mkdir()
    conf_file = conf_dir / "vbc.yaml"
    
    content = {
        'general': {
            'threads': 1, # Zostawiam 1 wątek dla stabilności GPU w teście
            'cq': 45,
            'gpu': True, # Włączamy GPU
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

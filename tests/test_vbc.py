import pytest
import subprocess
import os
import sys
from pathlib import Path

# Dodanie katalogu video do sys.path
sys.path.append(str(Path(__file__).parent.parent / "video"))
from vbc import load_config, ThreadController

# Pomocnicza funkcja do uruchamiania vbc w testach
def run_vbc(args):
    """Uruchamia vbc.py przy użyciu uv run"""
    # Usuwamy wymuszanie 1 wątku, pozwalamy na 2 zgodnie z życzeniem
    cmd = ["uv", "run", "python", "video/vbc.py"] + args
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result

# --- TESTY JEDNOSTKOWE ---

def test_config_loading(vbc_yaml):
    cfg = load_config(vbc_yaml)
    assert cfg['threads'] == 2
    assert cfg['dynamic_cq']['DC-GH7'] == 30

def test_thread_controller():
    tc = ThreadController(initial_threads=2, max_threads_limit=4)
    assert tc.get_current() == 2
    tc.increase()
    assert tc.get_current() == 3
    tc.decrease()
    assert tc.get_current() == 2

# --- TESTY E2E ---

def test_e2e_cq_quality_progression(test_data_dir, vbc_yaml):
    """Size(CQ20) > Size(CQ40) > Size(CQ60)"""
    output_dir = Path(f"{test_data_dir}_out")
    results = {}
    
    # Używamy plików Sony do testu jakości
    for cq in [20, 40, 60]:
        res = run_vbc([
            str(test_data_dir), "--min-size", "0", 
            "--cq", str(cq), "--config", str(vbc_yaml),
            "--camera", "ILCE-7RM5"
        ])
        
        out_file = output_dir / "sony_test.mp4"
        assert out_file.exists(), f"Brak pliku dla CQ{cq}. STDERR: {res.stderr}"
        results[cq] = out_file.stat().st_size
        out_file.unlink()

    print(f"\nSizes Sony: {results}")
    assert results[20] > results[40]
    assert results[40] > results[60]

def test_e2e_camera_filtering(test_data_dir, vbc_yaml):
    """Test filtracji --camera (powinno zostać tylko DJI)"""
    run_vbc([
        str(test_data_dir), "--min-size", "0", 
        "--camera", "DJI", "--config", str(vbc_yaml)
    ])
    
    out_dir = Path(f"{test_data_dir}_out")
    assert (out_dir / "dji_test.mp4").exists(), "DJI should be processed"
    assert not (out_dir / "gh7_test.mp4").exists(), "GH7 should be filtered out"

def test_e2e_rotation_qvr(test_data_dir, vbc_yaml):
    """Test czy plik QVR wyzwala auto-rotację 180"""
    run_vbc([
        str(test_data_dir), "--min-size", "0", 
        "--config", str(vbc_yaml)
    ])
    
    # 1. Sprawdzamy czy plik powstał
    out_file = Path(f"{test_data_dir}_out") / "QVR_20250101_120000.mp4"
    assert out_file.exists()

    # 2. Sprawdzamy logi - to potwierdza dopasowanie wzorca i kąta
    log_file = Path(f"{test_data_dir}_out") / "compression.log"
    assert log_file.exists()
    log_content = log_file.read_text()
    assert "matched: QVR_20250101_120000.mp4 → 180°" in log_content

def test_e2e_metadata_preservation_gh7(test_data_dir, vbc_yaml):
    """Test czy metadane (model, maker, location) przetrwały w GH7"""
    run_vbc([
        str(test_data_dir), "--min-size", "0", 
        "--config", str(vbc_yaml), "--camera", "GH7"
    ])
    
    out_file = Path(f"{test_data_dir}_out") / "gh7_test.mp4"
    assert out_file.exists()
    
    # Sprawdzenie przez exiftool
    res = subprocess.run(["exiftool", "-G", "-s", "-Model", "-Make", "-GPSLatitude", str(out_file)], 
                         capture_output=True, text=True)
    
    assert "DC-GH7" in res.stdout
    assert any(p in res.stdout for p in ["Panasonic", "Pana"])
    assert "50" in res.stdout
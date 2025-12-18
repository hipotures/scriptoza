import pytest
import subprocess
import os
import sys
import csv
from pathlib import Path

# Dodanie katalogu video do sys.path
sys.path.append(str(Path(__file__).parent.parent / "video"))
from vbc import load_config, ThreadController, VideoCompressor

# Pomocnicza funkcja do uruchamiania vbc w testach
def run_vbc(args):
    """Uruchamia vbc.py przy użyciu bieżącego interpretera (bez uv run)"""
    # Ustawiamy VIRTUAL_ENV, aby vbc.py nie próbował się przeładowywać
    env = os.environ.copy()
    if not env.get('VIRTUAL_ENV'):
        env['VIRTUAL_ENV'] = sys.prefix
        
    cmd = [sys.executable, "video/vbc.py"] + args
    if "--threads" not in args:
        cmd += ["--threads", "1"]
    result = subprocess.run(cmd, capture_output=True, text=True, env=env)
    return result

def get_log(test_dir):
    log_path = Path(f"{test_dir}_out") / "compression.log"
    return log_path.read_text() if log_path.exists() else "Log not found"

def find_config_line(output: str, label: str) -> str:
    for line in output.splitlines():
        if label in line:
            return line
    return ""

def read_latest_report(out_dir: Path) -> list[dict]:
    reports = sorted(out_dir.glob("compression_report_*.csv"))
    assert reports, "Brak raportu CSV"
    report_path = reports[-1]
    with report_path.open(newline='') as csvfile:
        reader = csv.DictReader(csvfile)
        rows = list(reader)
        assert reader.fieldnames
    return rows

# --- TESTY JEDNOSTKOWE ---

def test_config_loading(vbc_yaml):
    cfg = load_config(vbc_yaml)
    assert cfg['threads'] == 1
    assert cfg['gpu'] is True

def test_thread_controller():
    tc = ThreadController(initial_threads=1, max_threads_limit=2)
    tc.increase()
    assert tc.get_current() == 2

# --- TESTY E2E ---

def test_e2e_cq_quality_progression(test_data_dir, vbc_yaml):
    """Size(CQ20) > Size(CQ40) > Size(CQ60)"""
    output_dir = Path(f"{test_data_dir}_out")
    results = {}
    
    # Używamy plików DJI do testu jakości
    for cq in [20, 40, 60]:
        res = run_vbc([
            str(test_data_dir), "--min-size", "0", 
            "--cq", str(cq), "--config", str(vbc_yaml),
            "--camera", "Pocket" # Szerszy filtr
        ])
        
        out_file = output_dir / "dji_test.mp4"
        if not out_file.exists():
            print(f"STDOUT: {res.stdout}")
            print(f"STDERR: {res.stderr}")
            pytest.fail(f"Brak pliku dla CQ{cq}. LOG: {get_log(test_data_dir)}")
            
        results[cq] = out_file.stat().st_size
        out_file.unlink()

    print(f"\nSizes DJI: {results}")
    assert results[20] > results[40]
    assert results[40] > results[60]

def test_e2e_camera_filtering(test_data_dir, vbc_yaml):
    run_vbc([
        str(test_data_dir), "--min-size", "0", 
        "--camera", "Pocket", "--config", str(vbc_yaml)
    ])
    
    out_dir = Path(f"{test_data_dir}_out")
    assert (out_dir / "dji_test.mp4").exists()
    assert not (out_dir / "gh7_test.mp4").exists()

def test_e2e_rotation_qvr(test_data_dir, vbc_yaml):
    run_vbc([
        str(test_data_dir), "--min-size", "0", 
        "--config", str(vbc_yaml)
    ])
    
    log_content = get_log(test_data_dir)
    assert "matched: QVR_20250101_120000.mp4 → 180°" in log_content

def test_e2e_metadata_preservation_gh7(test_data_dir, vbc_yaml):
    run_vbc([
        str(test_data_dir), "--min-size", "0", 
        "--config", str(vbc_yaml), "--camera", "GH7"
    ])
    
    out_file = Path(f"{test_data_dir}_out") / "gh7_test.mp4"
    assert out_file.exists()
    
    res = subprocess.run(["exiftool", "-G", "-s", "-Model", "-GPSLatitude", str(out_file)], 
                         capture_output=True, text=True)
    
    assert "DC-GH7" in res.stdout
    # Testujemy czy GPS przetrwał (sprawdzając nową metodę kopiowania w vbc.py)
    assert "50" in res.stdout

def test_show_config_cli_flags(test_data_dir, vbc_yaml):
    res = run_vbc([
        str(test_data_dir), "--show-config", "--config", str(vbc_yaml),
        "--threads", "2", "--cq", "33", "--cpu", "--no-metadata",
        "--skip-av1", "--min-size", "1234", "--camera", "GH7"
    ])

    assert res.returncode == 0, f"STDOUT: {res.stdout}\nSTDERR: {res.stderr}"
    threads_line = find_config_line(res.stdout, "Threads")
    cq_line = find_config_line(res.stdout, "AV1 Quality")
    gpu_line = find_config_line(res.stdout, "GPU Acceleration")
    metadata_line = find_config_line(res.stdout, "Copy Metadata")
    skip_av1_line = find_config_line(res.stdout, "Skip AV1")
    min_size_line = find_config_line(res.stdout, "Min File Size")
    camera_line = find_config_line(res.stdout, "Camera Filters")

    assert threads_line and "2" in threads_line
    assert cq_line and "33" in cq_line
    assert gpu_line and "False" in gpu_line
    assert metadata_line and "False" in metadata_line
    assert skip_av1_line and "True" in skip_av1_line
    assert min_size_line and "1.2KB" in min_size_line
    assert camera_line and "GH7" in camera_line

def test_no_exif_camera_forces_warning(test_data_dir, vbc_yaml):
    res = run_vbc([
        str(test_data_dir), "--show-config", "--config", str(vbc_yaml),
        "--no-exif", "--camera", "GH7"
    ])

    assert res.returncode == 0, f"STDOUT: {res.stdout}\nSTDERR: {res.stderr}"
    assert "Warning: Camera filtering requires EXIF analysis." in res.stdout
    exif_line = find_config_line(res.stdout, "Use ExifTool Analysis")
    assert exif_line and "True" in exif_line

def test_report_generates_csv(test_data_dir, vbc_yaml):
    res = run_vbc([
        str(test_data_dir), "--report", "--config", str(vbc_yaml)
    ])

    assert res.returncode == 0, f"STDOUT: {res.stdout}\nSTDERR: {res.stderr}"
    out_dir = Path(f"{test_data_dir}_out")
    rows = read_latest_report(out_dir)
    assert rows
    assert "File" in rows[0]
    assert "Status" in rows[0]
    assert len(rows) >= 4

def test_report_camera_filter_multiple_values(test_data_dir, vbc_yaml):
    res = run_vbc([
        str(test_data_dir), "--report", "--config", str(vbc_yaml),
        "--camera", "ILCE-7RM5, DJI OsmoPocket3"
    ])

    assert res.returncode == 0, f"STDOUT: {res.stdout}\nSTDERR: {res.stderr}"
    out_dir = Path(f"{test_data_dir}_out")
    rows = read_latest_report(out_dir)
    rows_by_file = {row["File"]: row for row in rows}

    assert rows_by_file["sony_test.mp4"]["Camera Match"] == "Yes"
    assert rows_by_file["dji_test.mp4"]["Camera Match"] == "Yes"
    assert rows_by_file["gh7_test.mp4"]["Camera Match"] == "No"
    assert rows_by_file["gh7_test.mp4"]["Status"] == "Filtered Out"

def test_report_camera_filter_case_insensitive(test_data_dir, vbc_yaml):
    res = run_vbc([
        str(test_data_dir), "--report", "--config", str(vbc_yaml),
        "--camera", "dJi osMoPockEt3"
    ])

    assert res.returncode == 0, f"STDOUT: {res.stdout}\nSTDERR: {res.stderr}"
    out_dir = Path(f"{test_data_dir}_out")
    rows = read_latest_report(out_dir)
    rows_by_file = {row["File"]: row for row in rows}

    assert rows_by_file["dji_test.mp4"]["Camera Match"] == "Yes"
    assert rows_by_file["sony_test.mp4"]["Camera Match"] == "No"
    assert rows_by_file["gh7_test.mp4"]["Camera Match"] == "No"

def test_invalid_min_size_rejected(test_data_dir, vbc_yaml):
    res = run_vbc([
        str(test_data_dir), "--min-size", "-1", "--config", str(vbc_yaml)
    ])
    assert res.returncode != 0
    assert "Error: --min-size cannot be negative" in res.stdout

def test_missing_input_dir_rejected(vbc_yaml, tmp_path):
    missing_dir = tmp_path / "missing_input"
    res = run_vbc([
        str(missing_dir), "--config", str(vbc_yaml)
    ])
    assert res.returncode != 0
    assert "Error: Input directory does not exist" in res.stdout

def test_video_compressor_params(tmp_path):
    input_dir = tmp_path / "input"
    input_dir.mkdir()

    vc = VideoCompressor(
        input_dir=input_dir,
        threads=3,
        cq=22,
        rotate_180=True,
        use_cpu=True,
        prefetch_factor=4,
        copy_metadata=False,
        extensions=["mp4"],
        autorotate_patterns={"QVR_.*": 180},
        min_size_bytes=123,
        clean_errors=True,
        skip_av1=True,
        strip_unicode_display=False,
        use_exif=False,
        dynamic_cq={"DC-GH7": 30},
        filter_cameras=["GH7"]
    )

    assert vc.thread_controller.get_current() == 3
    assert vc.cq == 22
    assert vc.rotate_180 is True
    assert vc.use_cpu is True
    assert vc.prefetch_factor == 4
    assert vc.copy_metadata is False
    assert vc.extensions == ["mp4"]
    assert vc.autorotate_patterns == {"QVR_.*": 180}
    assert vc.min_size_bytes == 123
    assert vc.clean_errors is True
    assert vc.skip_av1 is True
    assert vc.strip_unicode_display is False
    assert vc.use_exif is False
    assert vc.dynamic_cq == {"DC-GH7": 30}
    assert vc.filter_cameras == ["GH7"]

def test_sanitize_filename_for_display(tmp_path):
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    name = "name_é.mp4"

    vc_strip = VideoCompressor(
        input_dir=input_dir,
        threads=1,
        cq=45,
        rotate_180=False,
        use_cpu=True,
        prefetch_factor=1,
        copy_metadata=False,
        extensions=["mp4"],
        autorotate_patterns={},
        min_size_bytes=0,
        clean_errors=False,
        skip_av1=False,
        strip_unicode_display=True,
        use_exif=False,
        dynamic_cq={},
        filter_cameras=[]
    )
    assert vc_strip.sanitize_filename_for_display(name) == "name_?.mp4"

    vc_keep = VideoCompressor(
        input_dir=input_dir,
        threads=1,
        cq=45,
        rotate_180=False,
        use_cpu=True,
        prefetch_factor=1,
        copy_metadata=False,
        extensions=["mp4"],
        autorotate_patterns={},
        min_size_bytes=0,
        clean_errors=False,
        skip_av1=False,
        strip_unicode_display=False,
        use_exif=False,
        dynamic_cq={},
        filter_cameras=[]
    )
    assert vc_keep.sanitize_filename_for_display(name) == name

"""보존할 원본·작업 데이터와 재생성 가능한 출력 경로."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / 'data' / 'portrait_editor'
RIG_DIR = DATA_DIR / 'rig'
WORKSPACE_DIR = DATA_DIR / 'workspace'
EXPORT_DIR = DATA_DIR / 'exports'
OUTPUT_DIR = ROOT / 'output' / 'portrait_editor'

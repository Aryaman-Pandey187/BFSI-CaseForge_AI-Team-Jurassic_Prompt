import os
import sys
from pathlib import Path

os.environ.setdefault("LLM_MODE", "mock")
os.environ.setdefault("DATA_BACKEND", "memory")
os.environ.setdefault("SIMULATOR_TURN_DELAY_S", "0")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

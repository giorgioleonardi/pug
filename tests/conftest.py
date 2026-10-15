import sys
from pathlib import Path

# Make the repo root importable (main.py and core/) without requiring `pip install -e .`.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Markers (network, anthropic) are registered in pytest.ini.

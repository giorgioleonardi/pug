import sys
from pathlib import Path

# Make the repo root importable (main.py and core/) without requiring `pip install -e .`.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def pytest_configure(config):
    config.addinivalue_line("markers", "network: needs internet access (calls jsonplaceholder.typicode.com)")

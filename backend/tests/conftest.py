import os
from pathlib import Path

os.environ["FRI_DB_PATH"] = str(Path(__file__).parent / "test.db")

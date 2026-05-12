"""pytest conftest: makes the parent module dir importable without
declaring the tests folder as a package (avoids collisions with other
`tests` folders elsewhere in the repo)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

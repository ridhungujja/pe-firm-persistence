"""Make the analysis scripts importable from tests.

The attenuation estimator lives in analysis/run_overlap.py rather than the
package because it is specific to the two-plan comparison, but it still needs
a validation path, so the directory goes on the path for tests.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "analysis"))


import pytest


@pytest.fixture(scope="session")
def repo_data():
    """The repository's data directory, for tests that check shipped tables."""
    return Path(__file__).resolve().parents[1] / "data"

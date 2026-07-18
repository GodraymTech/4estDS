from __future__ import annotations

import json
import subprocess
import sys


def test_importing_infer_does_not_load_optional_detector_stack() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import json, sys; "
                "import forestds.engine.infer; "
                "print(json.dumps({name: name in sys.modules "
                "for name in ('torch', 'ultralytics')}))"
            ),
        ],
        capture_output=True,
        check=False,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"torch": False, "ultralytics": False}


def test_utils_progress_import_is_lightweight_and_image_export_remains_usable() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import json, os, sys, tempfile; "
                "from pathlib import Path; "
                "from PIL import Image; "
                "from forestds.utils.progress import track_progress; "
                "from forestds.utils import get_image_dimensions; "
                "fd, filename = tempfile.mkstemp(suffix='.png'); "
                "os.close(fd); path = Path(filename); "
                "Image.new('RGB', (3, 2)).save(path); "
                "dimensions = get_image_dimensions(path); os.unlink(path); "
                "print(json.dumps({'dimensions': dimensions, "
                "'torch': 'torch' in sys.modules, "
                "'ultralytics': 'ultralytics' in sys.modules}))"
            ),
        ],
        capture_output=True,
        check=False,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "dimensions": [3, 2],
        "torch": False,
        "ultralytics": False,
    }

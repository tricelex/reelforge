"""Async FFmpeg service functions for video assembly.

All functions use asyncio.create_subprocess_exec. Inputs and outputs are
plain types (bytes, Path, float) — no StageContext or Django ORM dependency.
"""

import asyncio
import json
import tempfile
from pathlib import Path
from typing import Any

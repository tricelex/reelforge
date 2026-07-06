#!/usr/bin/env python3
"""Download curated fonts into this directory.

Handles Google Fonts repo layout changes: static files where available,
variable-font instancing via fonttools where not.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

# (remote URL, local filename, optional varLib instancer args)
_FONT_SOURCES: list[tuple[str, str, str | None]] = [
    (
        'https://github.com/google/fonts/raw/main/ofl/montserrat/Montserrat%5Bwght%5D.ttf',
        'Montserrat-Bold.ttf',
        'wght=700',
    ),
    (
        'https://github.com/google/fonts/raw/main/ofl/poppins/Poppins-Bold.ttf',
        'Poppins-Bold.ttf',
        None,
    ),
    (
        'https://github.com/google/fonts/raw/main/ofl/inter/Inter%5Bopsz,wght%5D.ttf',
        'Inter-Bold.ttf',
        'wght=700',
    ),
    (
        'https://github.com/google/fonts/raw/main/ofl/roboto/Roboto%5Bwdth,wght%5D.ttf',
        'Roboto-Bold.ttf',
        'wght=700',
    ),
    (
        'https://github.com/google/fonts/raw/main/ofl/oswald/Oswald%5Bwght%5D.ttf',
        'Oswald-Bold.ttf',
        'wght=700',
    ),
    (
        'https://github.com/google/fonts/raw/main/ofl/bebasneue/BebasNeue-Regular.ttf',
        'BebasNeue-Regular.ttf',
        None,
    ),
    (
        'https://github.com/google/fonts/raw/main/ofl/anton/Anton-Regular.ttf',
        'Anton-Regular.ttf',
        None,
    ),
    (
        'https://github.com/google/fonts/raw/main/ofl/archivoblack/ArchivoBlack-Regular.ttf',
        'ArchivoBlack-Regular.ttf',
        None,
    ),
    (
        'https://github.com/google/fonts/raw/main/ofl/bangers/Bangers-Regular.ttf',
        'Bangers-Regular.ttf',
        None,
    ),
    (
        'https://github.com/google/fonts/raw/main/apache/permanentmarker/PermanentMarker-Regular.ttf',
        'PermanentMarker-Regular.ttf',
        None,
    ),
    (
        'https://github.com/google/fonts/raw/main/ofl/caveat/Caveat%5Bwght%5D.ttf',
        'Caveat-Bold.ttf',
        'wght=700',
    ),
    (
        'https://github.com/google/fonts/raw/main/ofl/lobster/Lobster-Regular.ttf',
        'Lobster-Regular.ttf',
        None,
    ),
    (
        'https://github.com/google/fonts/raw/main/ofl/playfairdisplay/PlayfairDisplay%5Bwght%5D.ttf',
        'PlayfairDisplay-Bold.ttf',
        'wght=700',
    ),
    (
        'https://github.com/google/fonts/raw/main/ofl/righteous/Righteous-Regular.ttf',
        'Righteous-Regular.ttf',
        None,
    ),
    (
        'https://github.com/google/fonts/raw/main/apache/luckiestguy/LuckiestGuy-Regular.ttf',
        'LuckiestGuy-Regular.ttf',
        None,
    ),
    (
        'https://github.com/google/fonts/raw/main/ofl/pacifico/Pacifico-Regular.ttf',
        'Pacifico-Regular.ttf',
        None,
    ),
]


def _download(url: str, dest: Path) -> None:
    print(f'Fetching {url} -> {dest.name}')
    with urllib.request.urlopen(url) as response:  # noqa: S310
        dest.write_bytes(response.read())


def _instance_variable(src: Path, dest: Path, args: str) -> None:
    cmd = [
        sys.executable,
        '-m',
        'fontTools.varLib.instancer',
        str(src),
        args,
        '-o',
        str(dest),
    ]
    subprocess.run(cmd, check=True)  # noqa: S603


def main() -> None:
    """Download all curated font files into this package directory."""
    fonts_dir = Path(__file__).parent
    for url, filename, instance_args in _FONT_SOURCES:
        dest = fonts_dir / filename
        if dest.exists():
            print(f'Skip existing {filename}')
            continue
        if instance_args is None:
            _download(url, dest)
            continue
        with tempfile.TemporaryDirectory() as tmp:
            var_path = Path(tmp) / 'variable.ttf'
            _download(url, var_path)
            _instance_variable(var_path, dest, instance_args)
    print('Done.')


if __name__ == '__main__':
    main()

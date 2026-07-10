from __future__ import annotations

import sys
from pathlib import Path


DESKTOP_PET_ARG = "--desktop-pet"


def run_desktop_pet() -> None:
    pet_dir = Path(__file__).resolve().parent / "desktop_pet"
    if str(pet_dir) not in sys.path:
        sys.path.insert(0, str(pet_dir))

    from src.main import main as pet_main

    pet_main()


def run_downloader() -> None:
    from jm_app.main import main

    main()


if __name__ == "__main__":
    if DESKTOP_PET_ARG in sys.argv:
        sys.argv = [arg for arg in sys.argv if arg != DESKTOP_PET_ARG]
        run_desktop_pet()
    else:
        run_downloader()

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DOWNLOAD_DIR = BASE_DIR / "downloads"


def ensure_download_dir():
    """Ensures the download directory exists."""
    DOWNLOAD_DIR.mkdir(exist_ok=True)


def get_save_path(file_name: str) -> Path:
    """Returns the full path to save a file."""
    return DOWNLOAD_DIR / file_name

import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
API_ID = os.getenv("API_ID")       # Optional, for userbot features
API_HASH = os.getenv("API_HASH")   # Optional, for userbot features

# Encryption constants
PBKDF2_ITERATIONS = 600_000
ALGORITHM = "AES-256-GCM"
SALT_SIZE = 32
NONCE_SIZE = 12

# File size limits
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB Telegram bot API limit
CHUNK_SIZE = 49 * 1024 * 1024     # 49 MB chunks for large files

# Database
DATABASE_PATH = "cloud_storage.db"

# Folder structure
ROOT_FOLDER = "root"
FOLDERS = {
    "images": [".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".svg"],
    "pdfs": [".pdf"],
    "documents": [".doc", ".docx", ".txt", ".xlsx", ".pptx", ".csv"],
    "audio": [".mp3", ".wav", ".ogg", ".flac", ".aac"],
    "video": [".mp4", ".avi", ".mkv", ".mov", ".webm"],
    "archives": [".zip", ".rar", ".tar", ".gz", ".7z"],
    "other": []
}

ADMIN_IDS = [int(id) for id in os.getenv("ADMIN_IDS", "").split(",") if id]
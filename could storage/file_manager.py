import json
import random
import string
import os
from pathlib import Path
from typing import Optional

DB_FILE = Path("file_db.json")

class FileManager:
    def __init__(self):
        self.db = self._load_db()

    def _load_db(self) -> dict:
        if DB_FILE.exists():
            try:
                with open(DB_FILE, "r") as f:
                    return json.load(f)
            except json.JSONDecodeError:
                return {}
        return {}

    def _save_db(self):
        with open(DB_FILE, "w") as f:
            json.dump(self.db, f, indent=4)

    def generate_code(self, length=6) -> str:
        """Generates a unique random code."""
        while True:
            code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=length))
            if code not in self.db:
                return code

    def save_file_record(self, file_path: str, user_id: int, original_name: str, folder: str = "/") -> str:
        """Saves file metadata and returns a unique code."""
        code = self.generate_code()
        self.db[code] = {
            "path": str(file_path),
            "owner_id": user_id,
            "name": original_name,
            "folder": folder
        }
        self._save_db()
        return code

    def get_file_path(self, code: str) -> Optional[str]:
        """Retrieves the file path for a given code."""
        record = self.db.get(code.upper())
        if isinstance(record, dict):
            return record.get("path")
        # Fallback for old format (if any)
        return record if isinstance(record, str) else None

    def get_user_files(self, user_id: int, folder: str = "/") -> list:
        """Returns a list of (code, name, type) tuples for the user in the current folder."""
        files = []
        for code, record in self.db.items():
            if isinstance(record, dict) and record.get("owner_id") == user_id:
                # Check if file is in the requested folder
                file_folder = record.get("folder", "/")
                if file_folder == folder:
                    files.append((code, record.get("name", "Unknown File"), "file"))
        return files

    def get_all_files(self) -> list:
        """Returns a list of all files for admin view: (code, name, owner_id)."""
        files = []
        for code, record in self.db.items():
            if isinstance(record, dict):
                files.append((code, record.get("name", "Unknown"), record.get("owner_id")))
        return files

    def search_files(self, query: str, user_id: Optional[int] = None) -> list:
        """Search files by name. If user_id is None, search all files (Admin)."""
        results = []
        query = query.lower()
        for code, record in self.db.items():
            if isinstance(record, dict):
                name = record.get("name", "").lower()
                owner = record.get("owner_id")
                
                if query in name:
                    if user_id is None:
                        # Admin search: return (code, name, owner)
                        results.append((code, record.get("name"), owner))
                    elif owner == user_id:
                        # User search: return (code, name, type)
                        results.append((code, record.get("name"), "file"))
        return results

    def rename_file(self, code: str, new_name: str, user_id: int) -> bool:
        """Renames a file if the user owns it."""
        code = code.upper()
        record = self.db.get(code)
        if isinstance(record, dict) and record.get("owner_id") == user_id:
            self.db[code]["name"] = new_name
            self._save_db()
            return True
        return False

    def delete_file(self, code: str, user_id: int) -> bool:
        """Deletes a file record and the physical file if owned by user."""
        code = code.upper()
        record = self.db.get(code)
        
        if isinstance(record, dict) and record.get("owner_id") == user_id:
            file_path = record.get("path")
            if file_path and os.path.exists(file_path):
                try:
                    os.remove(file_path)
                except OSError:
                    pass # File might be gone already
            
            del self.db[code]
            self._save_db()
            return True
        return False

    def delete_files_in_folder(self, user_id: int, folder_path: str):
        """Deletes all files belonging to user in the specified folder and subfolders."""
        to_delete = []
        for code, record in self.db.items():
            if isinstance(record, dict) and record.get("owner_id") == user_id:
                file_folder = record.get("folder", "/")
                # Check if file is in the folder or any subfolder
                if file_folder == folder_path or file_folder.startswith(folder_path + "/"):
                    to_delete.append(code)
        
        for code in to_delete:
            self.delete_file(code, user_id)

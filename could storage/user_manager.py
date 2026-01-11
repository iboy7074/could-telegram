import json
from pathlib import Path

USER_DB_FILE = Path("users.json")

class UserManager:
    def __init__(self):
        self.db = self._load_db()

    def _load_db(self) -> dict:
        if USER_DB_FILE.exists():
            try:
                with open(USER_DB_FILE, "r") as f:
                    return json.load(f)
            except json.JSONDecodeError:
                return {}
        return {}

    def _save_db(self):
        with open(USER_DB_FILE, "w") as f:
            json.dump(self.db, f, indent=4)

    def register(self, user_id: int, username: str) -> bool:
        """Registers a new user by ID."""
        uid_str = str(user_id)
        if uid_str in self.db:
            return False
        # Initialize with root folder
        self.db[uid_str] = {
            "username": username, 
            "web_password": None,
            "current_folder": "/",
            "folders": ["/"] 
        }
        self._save_db()
        return True

    def get_current_folder(self, user_id: int) -> str:
        uid_str = str(user_id)
        if uid_str in self.db:
            return self.db[uid_str].get("current_folder", "/")
        return "/"

    def set_current_folder(self, user_id: int, folder: str):
        uid_str = str(user_id)
        if uid_str in self.db:
            self.db[uid_str]["current_folder"] = folder
            self._save_db()

    def create_folder(self, user_id: int, folder_name: str) -> bool:
        uid_str = str(user_id)
        if uid_str in self.db:
            folders = self.db[uid_str].get("folders", ["/"])
            current = self.db[uid_str].get("current_folder", "/")
            
            # Simple path construction
            if current == "/":
                new_path = f"/{folder_name}"
            else:
                new_path = f"{current}/{folder_name}"
            
            if new_path not in folders:
                folders.append(new_path)
                self.db[uid_str]["folders"] = folders
                self._save_db()
                return True
        return False

    def get_subfolders(self, user_id: int, current_folder: str) -> list:
        uid_str = str(user_id)
        subfolders = []
        if uid_str in self.db:
            all_folders = self.db[uid_str].get("folders", ["/"])
            # Find direct children
            for f in all_folders:
                if f != current_folder and f.startswith(current_folder):
                    # Check if it's a direct child (no extra slashes)
                    relative = f[len(current_folder):].lstrip("/")
                    if "/" not in relative and relative:
                        subfolders.append(f)
        return subfolders

    def delete_folder(self, user_id: int, folder_path: str) -> bool:
        """Deletes a folder and all its subfolders."""
        uid_str = str(user_id)
        if uid_str in self.db:
            folders = self.db[uid_str].get("folders", ["/"])
            
            # Cannot delete root
            if folder_path == "/":
                return False
                
            # Find all folders to remove (exact match or subfolder)
            to_remove = []
            for f in folders:
                if f == folder_path or f.startswith(folder_path + "/"):
                    to_remove.append(f)
            
            if to_remove:
                for f in to_remove:
                    folders.remove(f)
                
                # If current folder was deleted, reset to root
                current = self.db[uid_str].get("current_folder", "/")
                if current == folder_path or current.startswith(folder_path + "/"):
                    self.db[uid_str]["current_folder"] = "/"
                    
                self.db[uid_str]["folders"] = folders
                self._save_db()
                return True
        return False

    def is_registered(self, user_id: int) -> bool:
        """Checks if user_id is registered."""
        return str(user_id) in self.db

    def set_web_password(self, user_id: int, password: str):
        """Sets a password for web login."""
        uid_str = str(user_id)
        if uid_str in self.db:
            self.db[uid_str]["web_password"] = password
            self._save_db()

    def validate_web_login(self, user_id: str, password: str) -> bool:
        """Validates web login credentials."""
        if user_id in self.db:
            return self.db[user_id].get("web_password") == password
    def set_admin(self, user_id: int, is_admin: bool = True):
        """Sets admin status for a user."""
        uid_str = str(user_id)
        if uid_str in self.db:
            self.db[uid_str]["is_admin"] = is_admin
            self._save_db()

    def is_admin(self, user_id: int) -> bool:
        """Checks if a user is an admin."""
        uid_str = str(user_id)
        if uid_str in self.db:
            return self.db[uid_str].get("is_admin", False)
        return False

    def get_all_users(self) -> list:
        """Returns a list of (user_id, username) tuples."""
        users = []
        for uid, data in self.db.items():
            users.append((uid, data.get("username", "Unknown")))
        return users

    def search_users(self, query: str) -> list:
        """Search users by ID or username."""
        results = []
        query = query.lower()
        for uid, data in self.db.items():
            username = data.get("username", "").lower()
            if query in uid or query in username:
                results.append((uid, data.get("username", "Unknown")))
        return results

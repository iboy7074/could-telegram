import sqlite3
import hashlib
import os
import uuid
from datetime import datetime, timedelta
from config import DATABASE_PATH, PBKDF2_ITERATIONS, SALT_SIZE


class Database:
    def __init__(self):
        self.db_path = DATABASE_PATH
        self.init_db()

    def get_conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def init_db(self):
        conn = self.get_conn()
        c = conn.cursor()

        c.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER UNIQUE NOT NULL,
                username TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                password_salt TEXT NOT NULL,
                encryption_key_salt TEXT NOT NULL,
                storage_used INTEGER DEFAULT 0,
                created_at TEXT DEFAULT (datetime('now')),
                last_login TEXT
            )
        """)

        c.execute("""
            CREATE TABLE IF NOT EXISTS folders (
                folder_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                parent_id INTEGER,
                is_secret INTEGER DEFAULT 0,
                secret_password_hash TEXT,
                secret_password_salt TEXT,
                created_at TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
                FOREIGN KEY (parent_id) REFERENCES folders(folder_id) ON DELETE SET NULL
            )
        """)

        c.execute("""
            CREATE TABLE IF NOT EXISTS files (
                file_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                folder_id INTEGER,
                telegram_file_id TEXT NOT NULL,
                telegram_file_unique_id TEXT,
                original_name TEXT NOT NULL,
                encrypted_name TEXT,
                mime_type TEXT,
                size INTEGER DEFAULT 0,
                compressed_size INTEGER,
                encrypted_size INTEGER,
                checksum_sha256 TEXT,
                encryption_iv TEXT,
                is_encrypted INTEGER DEFAULT 1,
                is_compressed INTEGER DEFAULT 1,
                tags TEXT,
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
                FOREIGN KEY (folder_id) REFERENCES folders(folder_id) ON DELETE SET NULL
            )
        """)

        c.execute("""
            CREATE TABLE IF NOT EXISTS shared_links (
                link_id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_id INTEGER NOT NULL,
                share_token TEXT UNIQUE NOT NULL,
                max_downloads INTEGER DEFAULT -1,
                downloads_count INTEGER DEFAULT 0,
                expires_at TEXT,
                created_at TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (file_id) REFERENCES files(file_id) ON DELETE CASCADE
            )
        """)

        c.execute("""
            CREATE TABLE IF NOT EXISTS activity_log (
                log_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                action TEXT NOT NULL,
                details TEXT,
                ip_address TEXT,
                created_at TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
            )
        """)

        c.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                telegram_id INTEGER PRIMARY KEY,
                encrypted_password TEXT NOT NULL,
                created_at TEXT DEFAULT (datetime('now')),
                last_active TEXT DEFAULT (datetime('now'))
            )
        """)

        conn.commit()
        conn.close()

    # ─── User Management ───────────────────────────────────────────────

    def register_user(self, telegram_id, username, password):
        conn = self.get_conn()
        c = conn.cursor()

        c.execute("SELECT user_id FROM users WHERE telegram_id = ?", (telegram_id,))
        if c.fetchone():
            conn.close()
            return False, "User already registered"

        salt = os.urandom(SALT_SIZE).hex()
        enc_salt = os.urandom(SALT_SIZE).hex()
        password_hash = hashlib.pbkdf2_hmac(
            'sha256', password.encode(), bytes.fromhex(salt), PBKDF2_ITERATIONS
        ).hex()

        c.execute("""
            INSERT INTO users (telegram_id, username, password_hash, password_salt, encryption_key_salt)
            VALUES (?, ?, ?, ?, ?)
        """, (telegram_id, username, password_hash, salt, enc_salt))

        user_id = c.lastrowid

        # Create default folders — first insert root, then use its actual id
        default_subfolders = ["images", "pdfs", "documents", "audio", "video", "archives", "other"]
        c.execute("""
            INSERT INTO folders (user_id, name, parent_id)
            VALUES (?, ?, ?)
        """, (user_id, "root", None))
        root_id = c.lastrowid

        for folder_name in default_subfolders:
            c.execute("""
                INSERT INTO folders (user_id, name, parent_id)
                VALUES (?, ?, ?)
            """, (user_id, folder_name, root_id))

        conn.commit()
        conn.close()
        return True, "Registration successful"

    def authenticate_user(self, telegram_id, password):
        conn = self.get_conn()
        c = conn.cursor()

        c.execute("SELECT user_id, password_hash, password_salt FROM users WHERE telegram_id = ?", (telegram_id,))
        user = c.fetchone()

        if not user:
            conn.close()
            return False, "User not found"

        password_hash = hashlib.pbkdf2_hmac(
            'sha256', password.encode(), bytes.fromhex(user['password_salt']), PBKDF2_ITERATIONS
        ).hex()

        if password_hash != user['password_hash']:
            conn.close()
            return False, "Invalid password"

        c.execute("UPDATE users SET last_login = datetime('now') WHERE user_id = ?", (user['user_id'],))
        conn.commit()
        conn.close()
        return True, "Login successful"

    def get_user(self, telegram_id):
        conn = self.get_conn()
        c = conn.cursor()
        c.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,))
        user = c.fetchone()
        conn.close()
        return dict(user) if user else None

    def get_user_by_id(self, user_id):
        conn = self.get_conn()
        c = conn.cursor()
        c.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        user = c.fetchone()
        conn.close()
        return dict(user) if user else None

    # ─── Folder Management ─────────────────────────────────────────────

    def create_folder(self, user_id, name, parent_id=None, is_secret=False, secret_password=None):
        conn = self.get_conn()
        c = conn.cursor()

        secret_hash = None
        secret_salt = None
        if is_secret and secret_password:
            secret_salt = os.urandom(SALT_SIZE).hex()
            secret_hash = hashlib.pbkdf2_hmac(
                'sha256', secret_password.encode(), bytes.fromhex(secret_salt), PBKDF2_ITERATIONS
            ).hex()

        c.execute("""
            INSERT INTO folders (user_id, name, parent_id, is_secret, secret_password_hash, secret_password_salt)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (user_id, name, parent_id, int(is_secret), secret_hash, secret_salt))

        folder_id = c.lastrowid
        conn.commit()
        conn.close()
        return folder_id

    def verify_secret_folder(self, folder_id, password):
        conn = self.get_conn()
        c = conn.cursor()
        c.execute("SELECT * FROM folders WHERE folder_id = ? AND is_secret = 1", (folder_id,))
        folder = c.fetchone()
        conn.close()

        if not folder:
            return False, "Folder not found or not secret"

        password_hash = hashlib.pbkdf2_hmac(
            'sha256', password.encode(), bytes.fromhex(folder['secret_password_salt']), PBKDF2_ITERATIONS
        ).hex()

        if password_hash != folder['secret_password_hash']:
            return False, "Invalid password"

        return True, "Access granted"

    def get_folders(self, user_id, parent_id=None):
        conn = self.get_conn()
        c = conn.cursor()
        if parent_id is not None:
            c.execute("SELECT * FROM folders WHERE user_id = ? AND parent_id = ? ORDER BY name", (user_id, parent_id))
        else:
            c.execute("SELECT * FROM folders WHERE user_id = ? ORDER BY name", (user_id,))
        folders = c.fetchall()
        conn.close()
        return [dict(f) for f in folders]

    def get_folder_by_name(self, user_id, name, parent_id=None):
        conn = self.get_conn()
        c = conn.cursor()
        if parent_id is not None:
            c.execute("SELECT * FROM folders WHERE user_id = ? AND name = ? AND parent_id = ?",
                      (user_id, name, parent_id))
        else:
            c.execute("SELECT * FROM folders WHERE user_id = ? AND name = ?", (user_id, name))
        folder = c.fetchone()
        conn.close()
        return dict(folder) if folder else None

    def get_folder_by_id(self, folder_id):
        conn = self.get_conn()
        c = conn.cursor()
        c.execute("SELECT * FROM folders WHERE folder_id = ?", (folder_id,))
        folder = c.fetchone()
        conn.close()
        return dict(folder) if folder else None

    def get_folder_for_extension(self, user_id, filename):
        """Auto-detect folder based on file extension."""
        ext = os.path.splitext(filename)[1].lower()
        from config import FOLDERS
        for folder_name, extensions in FOLDERS.items():
            if ext in extensions:
                folder = self.get_folder_by_name(user_id, folder_name, parent_id=1)
                if folder:
                    return folder
        return self.get_folder_by_name(user_id, "other", parent_id=1)

    # ─── File Management ───────────────────────────────────────────────

    def save_file_metadata(
        self,
        user_id,
        folder_id,
        telegram_file_id,
        telegram_file_unique_id,
        original_name,
        encrypted_name,
        mime_type,
        size,
        compressed_size,
        encrypted_size,
        checksum_sha256,
        encryption_iv,
        is_encrypted=1,
        is_compressed=1,
        tags=""
    ):
        """
        Save file metadata after successful encryption and upload to Telegram.

        Parameters:
            user_id (int): Owner of the file
            folder_id (int): Folder to place the file in
            telegram_file_id (str): Telegram file_id of the encrypted blob
            telegram_file_unique_id (str): Telegram unique file identifier
            original_name (str): Original filename before encryption
            encrypted_name (str): Name of the encrypted file on Telegram
            mime_type (str): MIME type of the original file
            size (int): Original file size in bytes
            compressed_size (int): Size after compression
            encrypted_size (int): Size after encryption
            checksum_sha256 (str): SHA-256 hash of encrypted data
            encryption_iv (str): Nonce + salt combined (hex)
            is_encrypted (int): 1 if encrypted, 0 if plaintext
            is_compressed (int): 1 if compressed, 0 if not
            tags (str): Optional tags for search

        Returns:
            int: The file_id of the saved record
        """
        conn = self.get_conn()
        c = conn.cursor()

        c.execute("""
            INSERT INTO files (
                user_id,
                folder_id,
                telegram_file_id,
                telegram_file_unique_id,
                original_name,
                encrypted_name,
                mime_type,
                size,
                compressed_size,
                encrypted_size,
                checksum_sha256,
                encryption_iv,
                is_encrypted,
                is_compressed,
                tags
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            user_id,
            folder_id,
            telegram_file_id,
            telegram_file_unique_id,
            original_name,
            encrypted_name,
            mime_type,
            size,
            compressed_size,
            encrypted_size,
            checksum_sha256,
            encryption_iv,
            is_encrypted,
            is_compressed,
            tags
        ))

        file_id = c.lastrowid

        # Update user storage usage
        c.execute("""
            UPDATE users SET storage_used = storage_used + ?
            WHERE user_id = ?
        """, (size, user_id))

        conn.commit()
        conn.close()
        return file_id

    def get_files_in_folder(self, user_id, folder_id):
        """Get all files in a specific folder, ordered by newest first."""
        conn = self.get_conn()
        c = conn.cursor()
        c.execute("""
            SELECT * FROM files
            WHERE user_id = ? AND folder_id = ?
            ORDER BY created_at DESC
        """, (user_id, folder_id))
        files = c.fetchall()
        conn.close()
        return [dict(f) for f in files]

    def get_file_by_id(self, file_id):
        """Get a single file by its file_id."""
        conn = self.get_conn()
        c = conn.cursor()
        c.execute("SELECT * FROM files WHERE file_id = ?", (file_id,))
        file = c.fetchone()
        conn.close()
        return dict(file) if file else None

    def get_user_files(self, user_id, limit=50, offset=0):
        """Get recent files for a user."""
        conn = self.get_conn()
        c = conn.cursor()
        c.execute("""
            SELECT f.*, fol.name as folder_name
            FROM files f
            LEFT JOIN folders fol ON f.folder_id = fol.folder_id
            WHERE f.user_id = ?
            ORDER BY f.created_at DESC
            LIMIT ? OFFSET ?
        """, (user_id, limit, offset))
        files = c.fetchall()
        conn.close()
        return [dict(f) for f in files]

    def search_files(self, user_id, query, limit=20):
        """Search files by original name."""
        conn = self.get_conn()
        c = conn.cursor()
        c.execute("""
            SELECT f.*, fol.name as folder_name
            FROM files f
            LEFT JOIN folders fol ON f.folder_id = fol.folder_id
            WHERE f.user_id = ? AND f.original_name LIKE ?
            ORDER BY f.created_at DESC
            LIMIT ?
        """, (user_id, f"%{query}%", limit))
        files = c.fetchall()
        conn.close()
        return [dict(f) for f in files]

    def update_file_name(self, file_id, user_id, new_name):
        """Rename a file."""
        conn = self.get_conn()
        c = conn.cursor()
        c.execute("""
            UPDATE files SET original_name = ?, updated_at = datetime('now')
            WHERE file_id = ? AND user_id = ?
        """, (new_name, file_id, user_id))
        conn.commit()
        conn.close()

    def delete_file(self, file_id):
        """Delete a file record and update storage stats."""
        conn = self.get_conn()
        c = conn.cursor()

        file = self.get_file_by_id(file_id)
        if not file:
            conn.close()
            return False

        # Subtract file size from user's storage
        c.execute("""
            UPDATE users SET storage_used = MAX(0, storage_used - ?)
            WHERE user_id = ?
        """, (file['size'], file['user_id']))

        # Delete the file record (cascades to shared_links)
        c.execute("DELETE FROM files WHERE file_id = ?", (file_id,))
        conn.commit()
        conn.close()
        return True

    # ─── Sharing ───────────────────────────────────────────────────────

    def create_share_link(self, file_id, max_downloads=-1, expires_in_hours=24):
        """Create a shareable download link for a file."""
        conn = self.get_conn()
        c = conn.cursor()

        token = uuid.uuid4().hex
        expires_at = (datetime.utcnow() + timedelta(hours=expires_in_hours)).isoformat()

        c.execute("""
            INSERT INTO shared_links (file_id, share_token, max_downloads, expires_at)
            VALUES (?, ?, ?, ?)
        """, (file_id, token, max_downloads, expires_at))

        link_id = c.lastrowid
        conn.commit()
        conn.close()
        return token

    def get_share_link(self, token):
        """Get share link details including file info."""
        conn = self.get_conn()
        c = conn.cursor()
        c.execute("""
            SELECT sl.*, f.*
            FROM shared_links sl
            JOIN files f ON sl.file_id = f.file_id
            WHERE sl.share_token = ?
        """, (token,))
        link = c.fetchone()
        conn.close()
        return dict(link) if link else None

    def increment_share_download(self, link_id):
        """Increment download count for a shared link."""
        conn = self.get_conn()
        c = conn.cursor()
        c.execute("""
            UPDATE shared_links SET downloads_count = downloads_count + 1
            WHERE link_id = ?
        """, (link_id,))
        conn.commit()
        conn.close()

    def revoke_share_link(self, token):
        """Delete a share link."""
        conn = self.get_conn()
        c = conn.cursor()
        c.execute("DELETE FROM shared_links WHERE share_token = ?", (token,))
        conn.commit()
        conn.close()

    # ─── Activity Logging ──────────────────────────────────────────────

    def log_activity(self, user_id, action, details=None, ip_address=None):
        """Log a user activity."""
        conn = self.get_conn()
        c = conn.cursor()
        c.execute("""
            INSERT INTO activity_log (user_id, action, details, ip_address)
            VALUES (?, ?, ?, ?)
        """, (user_id, action, details, ip_address))
        conn.commit()
        conn.close()

    def get_user_activity(self, user_id, limit=50):
        """Get recent activity for a user."""
        conn = self.get_conn()
        c = conn.cursor()
        c.execute("""
            SELECT * FROM activity_log
            WHERE user_id = ?
            ORDER BY created_at DESC
            LIMIT ?
        """, (user_id, limit))
        rows = c.fetchall()
        conn.close()
        return [dict(r) for r in rows]

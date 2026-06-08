#!/usr/bin/env python3
"""
Telegram Cloud Storage Bot
AES-256-GCM encrypted cloud storage using Telegram as backend.
Persistent sessions — survives Render free plan restarts.
"""

import os
import io
import asyncio
import hashlib
import base64
import logging
import threading
import sqlite3
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime, timedelta
from typing import Optional

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ConversationHandler,
    filters, ContextTypes
)

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives import hashes
from cryptography.fernet import Fernet

from config import BOT_TOKEN, MAX_FILE_SIZE, PBKDF2_ITERATIONS, SALT_SIZE, NONCE_SIZE, FOLDERS, ADMIN_IDS
from database import Database

# ─── Logging ────────────────────────────────────────────────────────────
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ─── Conversation States ────────────────────────────────────────────────
(REGISTER_USERNAME, REGISTER_PASSWORD, LOGIN_PASSWORD,
 CREATE_FOLDER_NAME, SECRET_FOLDER_PASSWORD,
 RENAME_FILE) = range(6)

# ─── Database Instance ──────────────────────────────────────────────────
db = Database()


# ══════════════════════════════════════════════════════════════════════════
# CRYPTO ENGINE
# ══════════════════════════════════════════════════════════════════════════

class CryptoEngine:
    """AES-256-GCM encryption with PBKDF2-SHA512 key derivation."""

    @staticmethod
    def _derive_key(password: str, salt: bytes) -> bytes:
        return hashlib.pbkdf2_hmac(
            'sha512', password.encode(), salt, PBKDF2_ITERATIONS, dklen=32
        )

    @staticmethod
    def compress(data: bytes) -> bytes:
        import zlib
        return zlib.compress(data, level=9)

    @staticmethod
    def decompress(data: bytes) -> bytes:
        import zlib
        return zlib.decompress(data)

    @staticmethod
    def encrypt(data: bytes, password: str, user_salt: bytes) -> dict:
        """Compress → Encrypt → Checksum. Returns metadata dict."""
        compressed = CryptoEngine.compress(data)
        salt = os.urandom(SALT_SIZE)
        combined = user_salt + salt
        key = CryptoEngine._derive_key(password, combined)
        nonce = os.urandom(NONCE_SIZE)
        aesgcm = AESGCM(key)
        ciphertext = aesgcm.encrypt(nonce, compressed, None)
        return {
            'ciphertext': ciphertext,
            'nonce': nonce.hex(),
            'salt': salt.hex(),
            'checksum': hashlib.sha256(ciphertext).hexdigest(),
            'original_size': len(data),
            'compressed_size': len(compressed),
            'encrypted_size': len(ciphertext),
            'is_compressed': 1
        }

    @staticmethod
    def decrypt(ciphertext: bytes, nonce_hex: str, salt_hex: str,
                password: str, user_salt: bytes) -> bytes:
        """Decrypt → Decompress. Returns original data."""
        nonce = bytes.fromhex(nonce_hex)
        salt = bytes.fromhex(salt_hex)
        combined = user_salt + salt
        key = CryptoEngine._derive_key(password, combined)
        aesgcm = AESGCM(key)
        compressed = aesgcm.decrypt(nonce, ciphertext, None)
        return CryptoEngine.decompress(compressed)

    @staticmethod
    def get_fernet_key() -> bytes:
        """Derive a Fernet-compatible key from BOT_TOKEN for session encryption."""
        raw = hashlib.sha256(BOT_TOKEN.encode()).digest()[:32]
        return base64.urlsafe_b64encode(raw)


# ══════════════════════════════════════════════════════════════════════════
# DATABASE — Session table addition
# ══════════════════════════════════════════════════════════════════════════



def save_session(telegram_id: int, password: str):
    """Encrypt and store the user's password for session persistence."""
    f = Fernet(CryptoEngine.get_fernet_key())
    encrypted = f.encrypt(password.encode())
    conn = db.get_conn()
    c = conn.cursor()
    c.execute("""
        INSERT OR REPLACE INTO sessions (telegram_id, encrypted_password, last_active)
        VALUES (?, ?, datetime('now'))
    """, (telegram_id, encrypted.decode()))
    conn.commit()
    conn.close()


def restore_session(telegram_id: int) -> Optional[str]:
    """Restore a saved session password. Returns None if expired or not found."""
    conn = db.get_conn()
    c = conn.cursor()
    c.execute("""
        SELECT encrypted_password, last_active FROM sessions WHERE telegram_id = ?
    """, (telegram_id,))
    row = c.fetchone()
    conn.close()
    if not row:
        return None

    # Check session age — expire after 7 days
    try:
        last_active = datetime.strptime(row[1], "%Y-%m-%d %H:%M:%S")
        if datetime.utcnow() - last_active > timedelta(days=7):
            # Session expired
            conn2 = db.get_conn()
            c2 = conn2.cursor()
            c2.execute("DELETE FROM sessions WHERE telegram_id = ?", (telegram_id,))
            conn2.commit()
            conn2.close()
            return None
    except Exception:
        pass

    try:
        f = Fernet(CryptoEngine.get_fernet_key())
        password = f.decrypt(row[0].encode()).decode()
        return password
    except Exception:
        return None


def touch_session(telegram_id: int):
    """Update last_active timestamp for a session."""
    conn = db.get_conn()
    c = conn.cursor()
    c.execute("UPDATE sessions SET last_active = datetime('now') WHERE telegram_id = ?",
              (telegram_id,))
    conn.commit()
    conn.close()


# ══════════════════════════════════════════════════════════════════════════
# HEALTH SERVER (for Render)
# ══════════════════════════════════════════════════════════════════════════

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/plain')
        self.end_headers()
        self.wfile.write(b'Cloud Storage Bot - Alive')
    def log_message(self, format, *args):
        pass

def run_health_server():
    port = int(os.environ.get('PORT', 10000))
    server = HTTPServer(('0.0.0.0', port), HealthHandler)
    logger.info(f"[Health] Server running on port {port}")
    server.serve_forever()


# ══════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════

def format_size(size: int) -> str:
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


async def ensure_auth(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """
    Check authentication. If not in memory, try to restore from database session.
    This is what makes the bot survive Render restarts.
    """
    telegram_id = update.effective_user.id

    # Already authenticated in memory
    if context.user_data.get('authenticated') and context.user_data.get('session_password'):
        touch_session(telegram_id)
        return True

    # Check if user exists
    user = db.get_user(telegram_id)
    if not user:
        msg = update.message or update.callback_query.message
        await msg.reply_text("❌ You need an account. Use /register")
        return False

    # Try to restore session from database
    password = restore_session(telegram_id)
    if password:
        context.user_data['authenticated'] = True
        context.user_data['user_id'] = telegram_id
        context.user_data['username'] = user['username']
        context.user_data['session_password'] = password
        context.user_data['unlocked_secrets'] = {}
        touch_session(telegram_id)
        logger.info(f"[Session] Restored for user {telegram_id}")
        return True

    # No valid session — ask user to login
    msg = update.message or update.callback_query.message
    await msg.reply_text(
        "❌ **Session expired.**\n\n"
        "Your session was lost because the server restarted.\n"
        "Send /login to re-authenticate.\n\n"
        "_Your encrypted files are still safe._"
    )
    return False


def folder_keyboard(folders: list, unlocked_secrets: dict = None):
    keyboard = []
    for f in folders:
        if f['is_secret']:
            is_unlocked = unlocked_secrets and f['folder_id'] in unlocked_secrets
            prefix = "🔓" if is_unlocked else "🔒"
            keyboard.append([InlineKeyboardButton(
                f"{prefix} {f['name']}", callback_data=f"folder_{f['folder_id']}"
            )])
        else:
            keyboard.append([InlineKeyboardButton(
                f"📂 {f['name']}", callback_data=f"folder_{f['folder_id']}"
            )])
    keyboard.append([InlineKeyboardButton("➕ New Folder", callback_data="new_folder")])
    return InlineKeyboardMarkup(keyboard)


def file_keyboard(files: list, folder_id: int):
    keyboard = []
    for f in files:
        keyboard.append([InlineKeyboardButton(
            f"📄 {f['original_name']} ({format_size(f['size'])})",
            callback_data=f"file_{f['file_id']}"
        )])
    keyboard.append([
        InlineKeyboardButton("⬆️ Upload", callback_data=f"upload_{folder_id}"),
        InlineKeyboardButton("🔙 Back", callback_data="back_folders")
    ])
    return InlineKeyboardMarkup(keyboard)


def file_actions_keyboard(file_id: int):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("⬇️ Download", callback_data=f"download_{file_id}"),
            InlineKeyboardButton("🔗 Share", callback_data=f"share_{file_id}")
        ],
        [
            InlineKeyboardButton("✏️ Rename", callback_data=f"rename_{file_id}"),
            InlineKeyboardButton("🗑 Delete", callback_data=f"delete_{file_id}")
        ],
        [InlineKeyboardButton("🔙 Back", callback_data=f"back_files")]
    ])


def get_folder_for_filename(filename: str, user_id: int):
    """Auto-detect folder based on file extension."""
    ext = os.path.splitext(filename)[1].lower()
    for folder_name, extensions in FOLDERS.items():
        if ext in extensions:
            folder = db.get_folder_by_name(user_id, folder_name)
            if folder:
                return folder
    return db.get_folder_by_name(user_id, "other")


# ══════════════════════════════════════════════════════════════════════════
# COMMAND HANDLERS
# ══════════════════════════════════════════════════════════════════════════

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = db.get_user(user_id)

    if user:
        await update.message.reply_text(
            f"👋 Welcome back, **{user['username']}**!\n"
            f"📊 `{format_size(user['storage_used'])}` used\n\n"
            "📁 /folders — Browse files\n"
            "⬆️ Send any file to upload\n"
            "📋 /files — Recent files\n"
            "🔑 /login — Re-login\n"
            "❓ /help — All commands"
        )
    else:
        await update.message.reply_text(
            "☁️ **Telegram Cloud Storage Bot**\n\n"
            "✅ AES-256-GCM encryption\n"
            "✅ Automatic compression\n"
            "✅ Secret folders with passwords\n"
            "✅ Saves your session across restarts\n\n"
            "📝 /register — Create account\n"
            "🔑 /login  — Login"
        )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📚 **Commands**\n\n"
        "**Account:**\n"
        "/register — Create account\n"
        "/login — Login\n"
        "/logout — Logout\n"
        "/profile — Your stats\n\n"
        "**Files:**\n"
        "/folders — Browse\n"
        "/files — Recent files\n"
        "/search <q> — Search\n"
        "Send any file/photo — Auto-upload\n\n"
        "**Features:**\n"
        "• Files auto-sort into images/, pdfs/, etc.\n"
        "• Secret folders need a password to open\n"
        "• Encrypted before leaving your device\n"
        "• Session saved — survives server restarts"
    )


async def profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await ensure_auth(update, context):
        return
    user = db.get_user(update.effective_user.id)
    if not user:
        return

    conn = db.get_conn()
    c = conn.cursor()
    c.execute("SELECT COUNT(*), COALESCE(SUM(size),0) FROM files WHERE user_id=?",
              (user['user_id'],))
    count, total = c.fetchone()
    conn.close()

    await update.message.reply_text(
        f"👤 **{user['username']}**\n"
        f"ID: `{user['telegram_id']}`\n"
        f"📅 Joined: {user['created_at'][:10]}\n\n"
        f"📊 **Storage**\n"
        f"Files: {count}\n"
        f"Used: {format_size(total)}\n"
        f"🔐 AES-256-GCM + PBKDF2-SHA512\n"
        f"📦 zlib compression (level 9)\n\n"
        f"_Session auto-restores after restarts_ ✓"
    )


# ─── Registration ───────────────────────────────────────────────────────

async def register(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if db.get_user(user_id):
        await update.message.reply_text("❌ Already registered. Use /login")
        return ConversationHandler.END
    await update.message.reply_text(
        "📝 **Register — Step 1/2**\n\nEnter a **username**:"
    )
    return REGISTER_USERNAME


async def reg_username(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.message.text.strip()
    if len(name) < 3 or len(name) > 30:
        await update.message.reply_text("3–30 characters. Try again:")
        return REGISTER_USERNAME
    context.user_data['reg_name'] = name
    await update.message.reply_text(
        f"📝 **Register — Step 2/2**\n\nUsername: `{name}`\n\n"
        "Enter a **password** (min 8 chars).\n"
        "⚠️ Used for encryption — cannot be recovered!"
    )
    return REGISTER_PASSWORD


async def reg_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pw = update.message.text.strip()
    if len(pw) < 8:
        await update.message.reply_text("❌ Min 8 characters. Try again:")
        return REGISTER_PASSWORD

    name = context.user_data.pop('reg_name')
    tid = update.effective_user.id
    loop = asyncio.get_event_loop()
    ok, msg = await loop.run_in_executor(None, db.register_user, tid, name, pw)
    if ok:
        # Auto-login
        context.user_data['authenticated'] = True
        context.user_data['user_id'] = tid
        context.user_data['username'] = name
        context.user_data['session_password'] = pw
        context.user_data['unlocked_secrets'] = {}
        save_session(tid, pw)  # ← Persistent session!

        await update.message.reply_text(
            f"✅ **Registered as `{name}`**\n\n"
            "🔐 Encrypted session saved.\n"
            "Your session will survive server restarts.\n\n"
            "📁 /folders — Get started"
        )
        db.log_activity(tid, "register", "New user")
    else:
        await update.message.reply_text(f"❌ {msg}")
    return ConversationHandler.END


# ─── Login ──────────────────────────────────────────────────────────────

async def login(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tid = update.effective_user.id
    if not db.get_user(tid):
        await update.message.reply_text("❌ No account. Use /register")
        return ConversationHandler.END

    # Try auto-restore first
    pw = restore_session(tid)
    if pw:
        user = db.get_user(tid)
        context.user_data['authenticated'] = True
        context.user_data['user_id'] = tid
        context.user_data['username'] = user['username']
        context.user_data['session_password'] = pw
        context.user_data['unlocked_secrets'] = {}
        touch_session(tid)
        await update.message.reply_text("✅ **Session restored automatically!**")
        return ConversationHandler.END

    await update.message.reply_text("🔑 Enter your password:")
    return LOGIN_PASSWORD


async def login_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pw = update.message.text.strip()
    tid = update.effective_user.id
    loop = asyncio.get_event_loop()
    ok, msg = await loop.run_in_executor(None, db.authenticate_user, tid, pw)
    if ok:
        user = db.get_user(tid)
        context.user_data['authenticated'] = True
        context.user_data['user_id'] = tid
        context.user_data['username'] = user['username']
        context.user_data['session_password'] = pw
        context.user_data['unlocked_secrets'] = {}
        save_session(tid, pw)  # ← Saved for next restart!
        await update.message.reply_text(
            f"✅ **Welcome back, {user['username']}**\n"
            f"📊 `{format_size(user['storage_used'])}` used\n\n"
            "📁 /folders — Browse\n"
            "⬆️ Send any file to upload"
        )
        db.log_activity(tid, "login", "Login successful")
    else:
        await update.message.reply_text(f"❌ {msg}")
    return ConversationHandler.END


async def logout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tid = update.effective_user.id
    context.user_data.clear()
    conn = db.get_conn()
    c = conn.cursor()
    c.execute("DELETE FROM sessions WHERE telegram_id = ?", (tid,))
    conn.commit()
    conn.close()
    await update.message.reply_text("👋 Logged out. Session deleted.")


# ─── Folder Navigation ──────────────────────────────────────────────────

async def folders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await ensure_auth(update, context):
        return
    user = db.get_user(update.effective_user.id)
    root = db.get_folder_by_name(user['user_id'], "root")
    root_id = root['folder_id'] if root else None
    folders_list = db.get_folders(user['user_id'], parent_id=root_id)
    await update.message.reply_text(
        "📁 **Your Folders**\n\n_Tap a folder to browse files:_",
        reply_markup=folder_keyboard(folders_list, context.user_data.get('unlocked_secrets'))
    )


async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Unified callback handler for all inline buttons."""
    query = update.callback_query
    await query.answer()

    if not await ensure_auth(update, context):
        return

    user = db.get_user(update.effective_user.id)
    if not user:
        return

    data = query.data
    unlocked = context.user_data.get('unlocked_secrets', {})

    # ── Back to folders ──
    def _get_root_folders():
        root = db.get_folder_by_name(user['user_id'], "root")
        root_id = root['folder_id'] if root else None
        return db.get_folders(user['user_id'], parent_id=root_id)

    if data == "back_folders":
        fl = _get_root_folders()
        await query.edit_message_text(
            "📁 **Your Folders**",
            reply_markup=folder_keyboard(fl, unlocked)
        )
        return

    if data == "back_files":
        fl = _get_root_folders()
        await query.edit_message_text(
            "📁 **Your Folders**",
            reply_markup=folder_keyboard(fl, unlocked)
        )
        return

    # ── New folder ──
    if data == "new_folder":
        await query.edit_message_text(
            "📁 **New Folder**\n\nEnter folder name.\n"
            "For secret folder, type: `secret:MyFolder`"
        )
        return CREATE_FOLDER_NAME

    # ── Folder selected ──
    if data.startswith("folder_"):
        fid = int(data.split("_")[1])
        all_f = db.get_folders(user['user_id'])
        target = next((f for f in all_f if f['folder_id'] == fid), None)
        if not target:
            await query.edit_message_text("Folder not found.")
            return

        # Check secret folder lock
        if target['is_secret'] and fid not in unlocked:
            context.user_data['pending_secret'] = fid
            await query.edit_message_text(
                f"🔒 **{target['name']}** is password-protected.\n"
                "Enter the folder password:",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔙 Back", callback_data="back_folders")
                ]])
            )
            return SECRET_FOLDER_PASSWORD

        # Show files in this folder
        files = db.get_files_in_folder(user['user_id'], fid)
        name = target['name']
        if not files:
            text = f"📂 **{name}**\n\n_Empty folder._"
        else:
            text = f"📂 **{name}** ({len(files)} files)"
        await query.edit_message_text(text, reply_markup=file_keyboard(files, fid))
        return

    # ── Upload to folder ──
    if data.startswith("upload_"):
        fid = int(data.split("_")[1])
        context.user_data['upload_to'] = fid
        await query.edit_message_text(
            "⬆️ **Upload**\n\nSend me the file, photo, or document."
        )
        return

    # ── File selected ──
    if data.startswith("file_"):
        fid = int(data.split("_")[1])
        file = db.get_file_by_id(fid)
        if not file:
            await query.edit_message_text("File not found.")
            return
        await query.edit_message_text(
            f"📄 **{file['original_name']}**\n\n"
            f"Size: {format_size(file['size'])}\n"
            f"Type: {file['mime_type'] or 'Unknown'}\n"
            f"🔐 Encrypted: ✅ AES-256-GCM\n"
            f"📦 Compressed: ✅ zlib\n"
            f"📅 {file['created_at'][:19]}\n"
            f"🔑 `{file['checksum_sha256'][:16]}...`",
            reply_markup=file_actions_keyboard(fid)
        )
        return

    # ── Download ──
    if data.startswith("download_"):
        fid = int(data.split("_")[1])
        file = db.get_file_by_id(fid)
        if not file or file['user_id'] != user['user_id']:
            await query.edit_message_text("Access denied.")
            return

        pw = context.user_data.get('session_password', '')
        if not pw:
            await query.edit_message_text("❌ Session lost. /login")
            return

        await query.edit_message_text(f"⬇️ Decrypting `{file['original_name']}`...")

        try:
            # Download encrypted blob from Telegram
            fobj = await context.bot.get_file(file['telegram_file_id'])
            enc_data = await fobj.download_as_bytearray()

            # Decrypt
            user_db = db.get_user(update.effective_user.id)
            user_salt = bytes.fromhex(user_db['encryption_key_salt'])
            # encryption_iv stores salt_hex (64 chars) + nonce_hex (24 chars)
            iv = file['encryption_iv']
            salt_hex = iv[:64]
            nonce_hex = iv[64:]
            plain = CryptoEngine.decrypt(
                bytes(enc_data),
                nonce_hex,
                salt_hex,
                pw,
                user_salt
            )

            # Send decrypted file
            buf = io.BytesIO(plain)
            buf.name = file['original_name']
            await query.message.reply_document(
                document=buf,
                filename=file['original_name'],
                caption="✅ Decrypted"
            )
            db.log_activity(user['user_id'], "download", file['original_name'])
        except Exception as e:
            logger.error(f"Download error: {e}")
            await query.edit_message_text(f"❌ Download failed: {e}")
        return

    # ── Share ──
    if data.startswith("share_"):
        fid = int(data.split("_")[1])
        file = db.get_file_by_id(fid)
        if file:
            token = db.create_share_link(fid, max_downloads=5, expires_in_hours=24)
            me = await context.bot.get_me()
            link = f"https://t.me/{me.username}?start=share_{token}"
            await query.edit_message_text(
                f"🔗 **Share Link**\n\n"
                f"File: {file['original_name']}\n"
                f"`{link}`\n\n"
                f"⏰ Expires: 24h · 📥 Max 5 downloads",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔙", callback_data=f"file_{fid}")
                ]])
            )
        return

    # ── Delete ──
    if data.startswith("delete_"):
        fid = int(data.split("_")[1])
        file = db.get_file_by_id(fid)
        if file:
            db.delete_file(fid)
            await query.edit_message_text(f"🗑 Deleted `{file['original_name']}`")
            db.log_activity(user['user_id'], "delete", file['original_name'])
        return

    # ── Rename ──
    if data.startswith("rename_"):
        fid = int(data.split("_")[1])
        context.user_data['rename_id'] = fid
        await query.edit_message_text("✏️ Enter new filename (with extension):")
        return RENAME_FILE


# ─── Create Folder ──────────────────────────────────────────────────────

async def create_folder_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = db.get_user(update.effective_user.id)
    if not user:
        return ConversationHandler.END

    text = update.message.text.strip()
    is_secret = False
    name = text

    if text.lower().startswith("secret:"):
        parts = text.split(":", 1)
        if len(parts) == 2:
            name = parts[1].strip()
            is_secret = True

    if not name or len(name) > 50:
        await update.message.reply_text("❌ Invalid name (max 50 chars)")
        return ConversationHandler.END

    if is_secret:
        context.user_data['secret_folder_name'] = name
        await update.message.reply_text(
            f"🔒 **Secret folder: {name}**\n\nEnter a password:"
        )
        return SECRET_FOLDER_PASSWORD

    root = db.get_folder_by_name(user['user_id'], "root")
    root_id = root['folder_id'] if root else None
    db.create_folder(user['user_id'], name, parent_id=root_id)
    await update.message.reply_text(f"✅ Folder `{name}` created!")
    db.log_activity(user['user_id'], "create_folder", name)
    return ConversationHandler.END


async def secret_folder_pw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = db.get_user(update.effective_user.id)
    if not user:
        return ConversationHandler.END

    pw = update.message.text.strip()
    if len(pw) < 4:
        await update.message.reply_text("❌ Min 4 characters")
        return SECRET_FOLDER_PASSWORD

    # Creating new secret folder
    if 'secret_folder_name' in context.user_data:
        name = context.user_data.pop('secret_folder_name')
        root = db.get_folder_by_name(user['user_id'], "root")
        root_id = root['folder_id'] if root else None
        fid = db.create_folder(user['user_id'], name, parent_id=root_id,
                               is_secret=True, secret_password=pw)
        unlocked = context.user_data.get('unlocked_secrets', {})
        unlocked[fid] = True
        context.user_data['unlocked_secrets'] = unlocked
        await update.message.reply_text(f"✅ Secret folder `{name}` created & unlocked!")
        return ConversationHandler.END

    # Unlocking existing secret folder
    if 'pending_secret' in context.user_data:
        fid = context.user_data.pop('pending_secret')
        ok, msg = db.verify_secret_folder(fid, pw)
        if ok:
            unlocked = context.user_data.get('unlocked_secrets', {})
            unlocked[fid] = True
            context.user_data['unlocked_secrets'] = unlocked
            files = db.get_files_in_folder(user['user_id'], fid)
            all_f = db.get_folders(user['user_id'])
            target = next((f for f in all_f if f['folder_id'] == fid), None)
            name = target['name'] if target else "Secret"
            await update.message.reply_text(
                f"🔓 **{name}** unlocked!",
                reply_markup=file_keyboard(files, fid)
            )
        else:
            await update.message.reply_text(f"❌ {msg}\nTry again:")
            return SECRET_FOLDER_PASSWORD

    return ConversationHandler.END


# ─── Rename File ────────────────────────────────────────────────────────

async def rename_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = db.get_user(update.effective_user.id)
    if not user:
        return ConversationHandler.END

    fid = context.user_data.get('rename_id')
    if not fid:
        return ConversationHandler.END

    new_name = update.message.text.strip()
    db.update_file_name(fid, user['user_id'], new_name)
    await update.message.reply_text(f"✅ Renamed to `{new_name}`")
    return ConversationHandler.END


# ─── File Upload ────────────────────────────────────────────────────────

async def handle_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle incoming documents, photos, videos, audio."""
    if not await ensure_auth(update, context):
        return

    user = db.get_user(update.effective_user.id)
    if not user:
        return

    # Extract file info from message
    file_obj = None
    file_name = None
    mime_type = None

    if update.message.document:
        file_obj = update.message.document
        file_name = file_obj.file_name or "document.bin"
        mime_type = file_obj.mime_type or "application/octet-stream"
    elif update.message.photo:
        file_obj = update.message.photo[-1]
        file_name = f"photo_{update.message.message_id}.jpg"
        mime_type = "image/jpeg"
    elif update.message.video:
        file_obj = update.message.video
        file_name = file_obj.file_name or f"video_{update.message.message_id}.mp4"
        mime_type = file_obj.mime_type or "video/mp4"
    elif update.message.audio:
        file_obj = update.message.audio
        file_name = file_obj.file_name or f"audio_{update.message.message_id}.mp3"
        mime_type = file_obj.mime_type or "audio/mpeg"
    elif update.message.voice:
        file_obj = update.message.voice
        file_name = f"voice_{update.message.message_id}.ogg"
        mime_type = "audio/ogg"
    else:
        await update.message.reply_text("Unsupported file type.")
        return

    # Auto-detect folder (or use user-selected folder)
    folder = get_folder_for_filename(file_name, user['user_id'])
    folder_id = folder['folder_id'] if folder else 1
    if context.user_data.get('upload_to'):
        folder_id = context.user_data.pop('upload_to')

    await update.message.reply_text(
        f"⬆️ Uploading `{file_name}` → 📂 {folder['name'] if folder else 'root'}\n"
        f"🔐 Encrypting & compressing..."
    )

    try:
        # Download raw file from Telegram
        tf = await file_obj.get_file()
        raw_data = await tf.download_as_bytearray()
        raw_data = bytes(raw_data)

        # Encrypt
        pw = context.user_data.get('session_password', '')
        if not pw:
            await update.message.reply_text("❌ Session lost. /login")
            return

        user_salt = bytes.fromhex(user['encryption_key_salt'])
        result = CryptoEngine.encrypt(raw_data, pw, user_salt)

        # Upload encrypted blob BACK to Telegram
        buf = io.BytesIO(result['ciphertext'])
        buf.name = f"{file_name}.enc"
        sent = await update.message.reply_document(
            document=buf,
            filename=buf.name,
            caption=f"🔐 Encrypted: {file_name}"
        )

        # Save metadata
        tid = sent.document.file_id
        tuid = sent.document.file_unique_id
        # For salt storage: prepend salt to nonce in DB for simplicity
        nonce_with_salt = result['salt'] + result['nonce']  # 64 hex chars salt + 24 hex chars nonce

        db.save_file_metadata(
            user_id=user['user_id'],
            folder_id=folder_id,
            telegram_file_id=tid,
            telegram_file_unique_id=tuid,
            original_name=file_name,
            encrypted_name=buf.name,
            mime_type=mime_type,
            size=result['original_size'],
            compressed_size=result['compressed_size'],
            encrypted_size=result['encrypted_size'],
            checksum_sha256=result['checksum'],
            encryption_iv=nonce_with_salt,  # Stores salt + nonce combined
            is_encrypted=1,
            is_compressed=result['is_compressed'],
            tags=""
        )

        savings = 100 - int(result['compressed_size'] / max(result['original_size'], 1) * 100)
        await update.message.reply_text(
            f"✅ **Upload complete!**\n"
            f"📄 `{file_name}`\n"
            f"📦 `{format_size(result['original_size'])}` → `{format_size(result['encrypted_size'])}`"
            f" ({savings}% saved)\n"
            f"🔐 AES-256-GCM ✅\n"
            f"🔑 `{result['checksum'][:16]}...`"
        )
        db.log_activity(user['user_id'], "upload", file_name)

    except Exception as e:
        logger.error(f"Upload error: {e}", exc_info=True)
        await update.message.reply_text(f"❌ Upload failed: {e}")


# ─── List & Search ──────────────────────────────────────────────────────

async def list_files(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await ensure_auth(update, context):
        return
    user = db.get_user(update.effective_user.id)
    if not user:
        return

    rows = db.get_user_files(user['user_id'], limit=20)

    if not rows:
        await update.message.reply_text("📂 No files yet. Send me one!")
        return

    text = "📋 **Recent Files**\n\n"
    for r in rows:
        text += f"📄 `{r['original_name']}`\n📂 {r['folder_name']} — {format_size(r['size'])}\n\n"
    await update.message.reply_text(text)


async def search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await ensure_auth(update, context):
        return
    q = " ".join(context.args) if context.args else ""
    if not q:
        await update.message.reply_text("Usage: /search <filename>")
        return

    user = db.get_user(update.effective_user.id)
    if not user:
        return

    rows = db.search_files(user['user_id'], q, limit=20)

    if not rows:
        await update.message.reply_text(f"No files matching `{q}`")
        return

    text = f"🔍 **Results for `{q}`**\n\n"
    for r in rows:
        text += f"📄 `{r['original_name']}` — 📂 {r['folder_name']} — {format_size(r['size'])}\n"
    await update.message.reply_text(text)


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Cancelled.")
    return ConversationHandler.END


# ══════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════

def main():
    # Start health server thread (for Render)
    ht = threading.Thread(target=run_health_server, daemon=True)
    ht.start()

    logger.info("[Bot] Starting Telegram Cloud Storage Bot...")

    app = Application.builder().token(BOT_TOKEN).build()

    # ── Conversation Handlers ──
    app.add_handler(ConversationHandler(
        entry_points=[CommandHandler("register", register)],
        states={
            REGISTER_USERNAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, reg_username)],
            REGISTER_PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, reg_password)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    ))

    app.add_handler(ConversationHandler(
        entry_points=[CommandHandler("login", login)],
        states={
            LOGIN_PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, login_password)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    ))

    app.add_handler(ConversationHandler(
        entry_points=[CallbackQueryHandler(callback_handler, pattern="^new_folder$")],
        states={
            CREATE_FOLDER_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, create_folder_text)],
            SECRET_FOLDER_PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, secret_folder_pw)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    ))

    app.add_handler(ConversationHandler(
        entry_points=[CallbackQueryHandler(callback_handler, pattern="^rename_")],
        states={
            RENAME_FILE: [MessageHandler(filters.TEXT & ~filters.COMMAND, rename_text)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    ))

    # ── Command Handlers ──
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("profile", profile))
    app.add_handler(CommandHandler("logout", logout))
    app.add_handler(CommandHandler("folders", folders))
    app.add_handler(CommandHandler("files", list_files))
    app.add_handler(CommandHandler("search", search))

    # ── File Upload Handler ──
    app.add_handler(MessageHandler(
        filters.Document.ALL | filters.PHOTO | filters.VIDEO | filters.AUDIO | filters.VOICE,
        handle_upload
    ))

    # ── Callback Handler ──
    app.add_handler(CallbackQueryHandler(callback_handler))

    # ── Error Handler ──
    async def on_error(update: Update, context: ContextTypes.DEFAULT_TYPE):
        logger.error(f"Update error: {context.error}", exc_info=context.error)
        if update and update.effective_message:
            await update.effective_message.reply_text("❌ Unexpected error. Try again.")

    app.add_error_handler(on_error)

    logger.info("[Bot] Ready. Polling for updates...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()

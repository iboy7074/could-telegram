from io import BytesIO
import os
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, jsonify, redirect, render_template, request, send_file, session, url_for
from werkzeug.utils import secure_filename

from file_manager import FileManager
from security import InvalidToken, decrypt_file_to_bytes, encrypt_file, make_salt
from telegram_storage import upload_to_telegram
from user_manager import UserManager
from utils import ensure_download_dir, get_save_path

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "super_secret_key_change_this")

user_manager = UserManager()
file_manager = FileManager()


def _current_user_id() -> int | None:
    if "user_id" not in session:
        return None
    return int(session["user_id"])


@app.route("/")
def index():
    user_id = _current_user_id()
    if user_id is not None:
        query = request.args.get("q")

        if query:
            files = file_manager.search_files(query, user_id)
        else:
            files = file_manager.get_user_files(user_id)

        is_admin = user_manager.is_admin(user_id)
        return render_template("index.html", files=files, is_admin=is_admin, query=query)
    return render_template("index.html")


@app.route("/register", methods=["POST"])
def register_web():
    user_id = request.form.get("user_id", "").strip()
    username = request.form.get("username", "").strip() or "WebUser"
    password = request.form.get("password", "")
    confirm_password = request.form.get("confirm_password", "")

    if not user_id.isdigit():
        return "Telegram User ID must contain only numbers. <a href='/'>Try again</a>", 400
    if len(password) < 8:
        return "Password must be at least 8 characters. <a href='/'>Try again</a>", 400
    if password != confirm_password:
        return "Passwords do not match. <a href='/'>Try again</a>", 400

    if not user_manager.register(user_id, username, password):
        return "Account already exists. <a href='/'>Login instead</a>", 409

    session["user_id"] = user_id
    return redirect(url_for("index"))


@app.route("/admin")
def admin():
    user_id = _current_user_id()
    if user_id is None:
        return redirect(url_for("index"))

    if not user_manager.is_admin(user_id):
        return "Access Denied: Admins only.", 403

    query = request.args.get("q")
    if query:
        users = user_manager.search_users(query)
        files = file_manager.search_files(query, None)
    else:
        users = user_manager.get_all_users()
        files = file_manager.get_all_files()

    user_map = {str(uid): username for uid, username in user_manager.get_all_users()}

    return render_template("admin.html", users=users, files=files, query=query, user_map=user_map)


@app.route("/api/admin/files")
def api_admin_files():
    user_id = _current_user_id()
    if user_id is None:
        return jsonify({"error": "Unauthorized"}), 401

    if not user_manager.is_admin(user_id):
        return jsonify({"error": "Forbidden"}), 403

    files = file_manager.get_all_files()
    user_map = {str(uid): username for uid, username in user_manager.get_all_users()}

    data = []
    for code, name, owner, encrypted in files:
        data.append(
            {
                "code": code,
                "name": name,
                "owner": owner,
                "owner_name": user_map.get(str(owner), "Unknown"),
                "encrypted": encrypted,
            }
        )

    return jsonify(data)


@app.route("/login", methods=["POST"])
def login():
    user_id = request.form.get("user_id", "").strip()
    password = request.form.get("password", "")

    if user_manager.validate_web_login(user_id, password):
        session["user_id"] = user_id
        return redirect(url_for("index"))
    return "Invalid credentials. <a href='/'>Try again</a>", 401


@app.route("/logout")
def logout():
    session.pop("user_id", None)
    return redirect(url_for("index"))


@app.route("/upload", methods=["POST"])
def upload():
    user_id = _current_user_id()
    if user_id is None:
        return redirect(url_for("index"))

    if "file" not in request.files:
        return "No file part", 400

    uploaded_file = request.files["file"]
    if uploaded_file.filename == "":
        return "No selected file", 400

    encryption_password = request.form.get("encryption_password", "")
    if len(encryption_password) < 8:
        return "Encryption password must be at least 8 characters. <a href='/'>Try again</a>", 400

    ensure_download_dir()
    original_name = secure_filename(uploaded_file.filename) or "upload.bin"
    encrypted_name = f"{original_name}.enc"
    save_path = Path(get_save_path(encrypted_name))
    salt = make_salt()
    encrypt_file(uploaded_file.stream, save_path, encryption_password, salt)

    telegram_metadata = upload_to_telegram(
        save_path,
        caption=f"Encrypted upload for {user_manager.get_username(user_id)}: {original_name}",
    )

    storage_backend = "telegram+local" if telegram_metadata else "local"
    file_manager.save_file_record(
        str(save_path),
        user_id,
        original_name,
        encrypted=True,
        encryption_salt=salt,
        storage_backend=storage_backend,
        telegram_file_id=telegram_metadata.get("file_id") if telegram_metadata else None,
        telegram_message_id=telegram_metadata.get("message_id") if telegram_metadata else None,
    )
    return redirect(url_for("index"))


@app.route("/download/<code>", methods=["GET", "POST"])
def download(code):
    user_id = _current_user_id()
    if user_id is None:
        return redirect(url_for("index"))

    record = file_manager.get_record(code)
    if not record or (record.get("owner_id") != user_id and not user_manager.is_admin(user_id)):
        return "File not found", 404

    path = record.get("path")
    if not path or not os.path.exists(path):
        return "File not found", 404

    if record.get("encrypted"):
        if request.method == "GET":
            return render_template("download_password.html", code=code, name=record.get("name", "file"))

        password = request.form.get("encryption_password", "")
        try:
            decrypted = decrypt_file_to_bytes(path, password, record.get("encryption_salt", ""))
        except (InvalidToken, ValueError):
            return "Wrong encryption password. <a href='javascript:history.back()'>Try again</a>", 403

        return send_file(
            BytesIO(decrypted),
            as_attachment=True,
            download_name=record.get("name", "download"),
        )

    return send_file(path, as_attachment=True, download_name=record.get("name"))


if __name__ == "__main__":
    app.run(debug=True, port=5001)

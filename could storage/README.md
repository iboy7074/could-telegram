# Telegram Cloud Storage Bot ☁️

A Telegram-backed cloud storage project with a Flask web app. Users can register or login with a Telegram user ID, upload files/photos from the web UI, protect uploads with a per-file encryption password, and manage stored files from a browser or bot.

## Features 🚀

### Telegram Bot
* **File Storage**: Send files, photos, videos, audio, or text to the bot to save them.
* **File Management**: Rename, delete, and organize files into folders.
* **Folder System**: Create directories (`/mkdir` flow), navigate, and list files from inline buttons.
* **Search**: Search for files using `/search`.
* **Web Login**: Set a hashed web password using `/setpassword <password>`.

### Web Dashboard
* **Register/Login**: Create a web account with Telegram user ID and password, or login after setting a bot password.
* **Encrypted Uploads**: Web uploads require a separate encryption password and are encrypted before being stored.
* **Optional Telegram Storage**: Configure `BOT_TOKEN` and `TELEGRAM_STORAGE_CHAT_ID` to send encrypted web uploads to a Telegram chat through the bot.
* **Protected Downloads**: Encrypted files require the original encryption password before download.
* **Admin Panel**: Admin users can view users and file metadata.

> Note: The web server receives the encryption password during upload/download to encrypt or decrypt the file, and it does not store that password. For strict browser-only end-to-end encryption, add client-side encryption before upload.

## Setup 🛠️

1. **Install Dependencies**
   ```bash
   pip install -r "could storage/requirements.txt"
   ```

2. **Environment Variables**
   Create a `.env` file in `could storage/`:
   ```env
   BOT_TOKEN=your_telegram_bot_token_here
   FLASK_SECRET_KEY=replace_with_a_random_secret

   # Optional: enables Telegram storage for encrypted web uploads.
   TELEGRAM_STORAGE_CHAT_ID=your_private_channel_or_chat_id
   ```

3. **Run the Bot**
   ```bash
   cd "could storage"
   python main.py
   ```

4. **Run the Web App**
   ```bash
   cd "could storage"
   python app.py
   ```

5. **Open the Website**
   Visit `http://localhost:5001`.

## Usage 📖

### Bot Commands
* `/start` - Initialize the bot.
* `/register` - Create a new Telegram bot account.
* `/home` - Show the main menu.
* `/list` - List files in the current directory.
* `/search <query>` - Search files.
* `/setpassword <password>` - Set or update your hashed web login password.
* `/admin_login <secret>` - Promote yourself to admin when you know the configured secret.

### Web Interface
1. Open `http://localhost:5001`.
2. Register with your Telegram user ID, or login with a password set through the bot.
3. Upload a file/photo and enter an encryption password.
4. Download encrypted files by entering the same encryption password.

## Project Structure 📂
* `could storage/main.py`: Telegram bot entry point.
* `could storage/app.py`: Flask web application.
* `could storage/security.py`: Password hashing and encryption helpers.
* `could storage/telegram_storage.py`: Optional Telegram upload integration.
* `could storage/file_manager.py`: File metadata persistence.
* `could storage/user_manager.py`: User registration and authentication.
* `could storage/templates/`: Web templates.

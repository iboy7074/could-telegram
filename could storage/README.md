# Telegram Cloud Storage Bot ☁️

A powerful Telegram bot that acts as your personal cloud storage, complete with a Web Admin Dashboard for easy file management.

## Features 🚀

### Telegram Bot
*   **File Storage**: Send any file or text to the bot to save it.
*   **File Management**: Rename, delete, and organize files into folders.
*   **Folder System**: Create directories (`/mkdir`), navigate (`/cd`), and view current path (`/pwd`).
*   **Search**: Search for files using `/search`.
*   **Web Login**: Set a password for the web dashboard using `/setpassword`.

### Web Dashboard
*   **File Browser**: View and download your files from a browser.
*   **Search**: Filter files by name.
*   **Admin Panel**: (Admin only) View all users and files in the system.
*   **Upload**: Upload files directly from the web interface.

## Setup 🛠️

1.  **Install Dependencies**
    ```bash
    pip install -r requirements.txt
    ```

2.  **Environment Variables**
    Create a `.env` file (see `.env.example`) and add your Telegram Bot Token:
    ```env
    BOT_TOKEN=your_telegram_bot_token_here
    ```

3.  **Run the Bot**
    Start the Telegram bot:
    ```bash
    python main.py
    ```

4.  **Run the Web App**
    Start the Flask web server (default port 5001):
    ```bash
    python app.py
    ```

## Usage 📖

### Bot Commands
*   `/start` - Initialize the bot.
*   `/register` - Create a new account.
*   `/home` - Show the main menu and help.
*   `/list` - List files in the current directory.
*   `/mkdir <name>` - Create a new folder.
*   `/cd <name>` - Change directory (`..` to go back).
*   `/delete <code>` - Delete a file by its code.
*   `/rename <code> <name>` - Rename a file.
*   `/setpassword <password>` - Set a password for web login.
*   `/admin_login <secret>` - Promote yourself to admin (Secret: `bharath`).

### Web Interface
1.  Open `http://localhost:5001` in your browser.
2.  Login with your Telegram User ID and the password you set via the bot.
3.  Admins can access the dashboard at `/admin`.

## Project Structure 📂
*   `main.py`: Telegram bot entry point.
*   `app.py`: Flask web application.
*   `file_manager.py`: Handles file operations and database interactions.
*   `user_manager.py`: Manages user authentication and data.
*   `templates/`: HTML templates for the web interface.

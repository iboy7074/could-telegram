
import os
import logging
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters, CallbackQueryHandler
from utils import ensure_download_dir, get_save_path
from file_manager import FileManager
from user_manager import UserManager

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# Global state
file_manager = FileManager()
user_manager = UserManager()

# User Interaction States
user_states = {}
user_context = {}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("🏠 Main Menu", callback_data='main_menu')],
        [InlineKeyboardButton("📝 Register", callback_data='register_info')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="Hi! I'm your Cloud Storage Bot.\n\n"
             "I can save your files and help you manage them.\n"
             "Click below to get started!",
        reply_markup=reply_markup
    )

async def register(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_chat.id
    username = update.effective_user.username or "Unknown"
    
    if user_manager.register(user_id, username):
        await update.message.reply_text(f"✅ Welcome {username}! You are now registered.\nYou can start sending files immediately.")
    else:
        await update.message.reply_text("You are already registered! Just send me files.")

async def home(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_main_menu(update, context)

async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("📂 My Files", callback_data='list_files')],
        [InlineKeyboardButton("📤 How to Upload", callback_data='upload_info')],
        [InlineKeyboardButton("🔍 Search", callback_data='search_prompt')],
        [InlineKeyboardButton("⚙️ Set Password", callback_data='password_info')],
        [InlineKeyboardButton("❓ Help", callback_data='help')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    text = "🏠 **Main Menu**\n\nSelect an option below:"
    
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(text=text, reply_markup=reply_markup, parse_mode='Markdown')
    else:
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='Markdown')

def get_file_list_markup(user_id: int, current_folder: str) -> InlineKeyboardMarkup:
    keyboard = []
    
    # Navigation
    if current_folder != "/":
        keyboard.append([InlineKeyboardButton("⬆️ Up", callback_data='cd:..')])
    
    keyboard.append([InlineKeyboardButton("🏠 Home", callback_data='main_menu'), InlineKeyboardButton("➕ New Folder", callback_data='mkdir_prompt')])
    
    # Delete Folder Option (if not root)
    if current_folder != "/":
        keyboard.append([InlineKeyboardButton("🗑️ Delete This Folder", callback_data='del_folder_confirm')])

    # Subfolders
    subfolders = user_manager.get_subfolders(user_id, current_folder)
    for f in subfolders:
        name = f.split("/")[-1]
        keyboard.append([InlineKeyboardButton(f"📁 {name}", callback_data=f"cd:{name}")])
        
    # Files
    files = file_manager.get_user_files(user_id, current_folder)
    for code, name, _ in files:
        keyboard.append([InlineKeyboardButton(f"📄 {name}", callback_data=f"file:{code}")])
        
    return InlineKeyboardMarkup(keyboard)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    # Don't answer immediately here, as some paths might need specific answers or alerts
    
    user_id = update.effective_chat.id
    
    if query.data == 'main_menu':
        await query.answer()
        await show_main_menu(update, context)
        
    elif query.data == 'register_info':
        await query.answer()
        await query.edit_message_text(
            text="To register, simply type `/register`.\n\nOnce registered, you can upload files and access the web dashboard.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data='main_menu')]])
        )
        
    elif query.data == 'help':
        await query.answer()
        help_text = (
            "❓ **Help & Commands**\n\n"
            "**Basics**\n"
            "`/start` - Restart bot\n"
            "`/register` - Create account\n"
            "`/home` - Show Main Menu\n\n"
            "**Interactive**\n"
            "Use the buttons to navigate, create folders, and manage files.\n"
            "The bot will ask you for input when needed."
        )
        await query.edit_message_text(
            text=help_text,
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data='main_menu')]])
        )
        
    elif query.data == 'upload_info':
        await query.answer()
        await query.edit_message_text(
            text="📤 **How to Upload**\n\n"
                 "1. Simply send any **File**, **Photo**, or **Video** to this chat.\n"
                 "2. Add a caption to name the file (optional).\n"
                 "3. Or send **Text** to create a text file.\n\n"
                 "Your file will be saved instantly!",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data='main_menu')]])
        )

    elif query.data == 'search_prompt':
        await query.answer()
        user_states[user_id] = "WAIT_SEARCH"
        await context.bot.send_message(chat_id=user_id, text="🔍 **Search**\n\nPlease type what you are looking for:")
        
    elif query.data == 'password_info':
        await query.answer()
        user_states[user_id] = "WAIT_PASSWORD"
        await context.bot.send_message(chat_id=user_id, text="⚙️ **Set Password**\n\nPlease type your new web password:")
        
    elif query.data == 'list_files':
        await query.answer()
        if not user_manager.is_registered(user_id):
            await query.edit_message_text("Please `/register` first.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data='main_menu')]]))
            return

        current_folder = user_manager.get_current_folder(user_id)
        reply_markup = get_file_list_markup(user_id, current_folder)
        
        await query.edit_message_text(
            text=f"📂 **Path: {current_folder}**", 
            parse_mode='Markdown',
            reply_markup=reply_markup
        )
        
    elif query.data.startswith('cd:'):
        await query.answer()
        target = query.data.split(':', 1)[1]
        current = user_manager.get_current_folder(user_id)
        
        if target == "..":
            if current != "/":
                parent = "/" + "/".join(current.strip("/").split("/")[:-1])
                if parent == "//": parent = "/"
                user_manager.set_current_folder(user_id, parent)
        else:
            # Enter folder
            if current == "/":
                new_path = f"/{target}"
            else:
                new_path = f"{current}/{target}"
            
            folders = user_manager.db[str(user_id)].get("folders", ["/"])
            if new_path in folders:
                user_manager.set_current_folder(user_id, new_path)
            else:
                await context.bot.answer_callback_query(query.id, text="Folder not found!", show_alert=True)
                return

        # Refresh list
        new_current = user_manager.get_current_folder(user_id)
        reply_markup = get_file_list_markup(user_id, new_current)
        await query.edit_message_text(
            text=f"📂 **Path: {new_current}**",
            parse_mode='Markdown',
            reply_markup=reply_markup
        )
        
    elif query.data.startswith('file:'):
        await query.answer()
        code = query.data.split(':')[1]
        file_path = file_manager.get_file_path(code)
        
        if not file_path:
            await query.edit_message_text("File not found.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data='list_files')]]))
            return
            
        # Get file info
        record = file_manager.db.get(code)
        name = record.get("name", "Unknown") if record else "Unknown"
        
        keyboard = [
            [InlineKeyboardButton("⬇️ Download", callback_data=f"dl:{code}")],
            [InlineKeyboardButton("✏️ Rename", callback_data=f"rename_prompt:{code}")],
            [InlineKeyboardButton("🗑️ Delete", callback_data=f"del_confirm:{code}")],
            [InlineKeyboardButton("🔙 Back", callback_data='list_files')]
        ]
        
        await query.edit_message_text(
            text=f"📄 **File Details**\n\n**Name:** {name}\n**Code:** `{code}`",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    elif query.data.startswith('rename_prompt:'):
        await query.answer()
        code = query.data.split(':')[1]
        user_states[user_id] = "WAIT_RENAME"
        user_context[user_id] = code
        await context.bot.send_message(
            chat_id=user_id, 
            text=f"✏️ **Rename File**\n\nPlease type the new name for file `{code}`:",
            parse_mode='Markdown'
        )

    elif query.data.startswith('dl:'):
        await query.answer()
        code = query.data.split(':')[1]
        path = file_manager.get_file_path(code)
        if path and os.path.exists(path):
            await context.bot.send_document(chat_id=user_id, document=open(path, 'rb'))
        else:
            await context.bot.answer_callback_query(query.id, text="File not found!", show_alert=True)

    elif query.data.startswith('del_confirm:'):
        await query.answer()
        code = query.data.split(':')[1]
        keyboard = [
            [InlineKeyboardButton("✅ Yes, Delete", callback_data=f"del:{code}")],
            [InlineKeyboardButton("❌ Cancel", callback_data=f"file:{code}")]
        ]
        await query.edit_message_text(
            text=f"⚠️ Are you sure you want to delete file `{code}`?",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    elif query.data.startswith('del:'):
        await query.answer()
        code = query.data.split(':')[1]
        if file_manager.delete_file(code, user_id):
            await context.bot.answer_callback_query(query.id, text="File deleted!", show_alert=True)
            # Return to list
            current_folder = user_manager.get_current_folder(user_id)
            reply_markup = get_file_list_markup(user_id, current_folder)
            await query.edit_message_text(
                text=f"📂 **Path: {current_folder}**",
                parse_mode='Markdown',
                reply_markup=reply_markup
            )
        else:
            await context.bot.answer_callback_query(query.id, text="Failed to delete.", show_alert=True)
            
    elif query.data == 'mkdir_prompt':
        await query.answer()
        user_states[user_id] = "WAIT_MKDIR"
        await context.bot.send_message(chat_id=user_id, text="📂 **New Folder**\n\nPlease type the name for the new folder:")

    elif query.data == 'del_folder_confirm':
        await query.answer()
        current_folder = user_manager.get_current_folder(user_id)
        if current_folder == "/":
            await context.bot.answer_callback_query(query.id, text="Cannot delete root!", show_alert=True)
            return
            
        keyboard = [
            [InlineKeyboardButton("✅ Yes, Delete Folder", callback_data='del_folder')],
            [InlineKeyboardButton("❌ Cancel", callback_data='list_files')]
        ]
        await query.edit_message_text(
            text=f"⚠️ **Delete Folder?**\n\nAre you sure you want to delete `{current_folder}` and ALL files inside it?",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    elif query.data == 'del_folder':
        await query.answer()
        current_folder = user_manager.get_current_folder(user_id)
        if current_folder == "/":
            await context.bot.answer_callback_query(query.id, text="Cannot delete root!", show_alert=True)
            return

        # Delete files first
        file_manager.delete_files_in_folder(user_id, current_folder)
        # Delete folder
        if user_manager.delete_folder(user_id, current_folder):
            await context.bot.answer_callback_query(query.id, text="Folder deleted!", show_alert=True)
            # Return to root (or parent, but logic resets to root if current deleted)
            new_current = user_manager.get_current_folder(user_id)
            reply_markup = get_file_list_markup(user_id, new_current)
            await query.edit_message_text(
                text=f"📂 **Path: {new_current}**",
                parse_mode='Markdown',
                reply_markup=reply_markup
            )
        else:
            await context.bot.answer_callback_query(query.id, text="Failed to delete folder.", show_alert=True)

def is_authorized(update: Update) -> bool:
    return user_manager.is_registered(update.effective_chat.id)

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        await update.message.reply_text("Please `/register` first.")
        return

    ensure_download_dir()
    
    attachment = update.message.effective_attachment
    
    if isinstance(attachment, (list, tuple)):
        file_obj = attachment[-1]
        file_name = f"{file_obj.file_unique_id}.jpg"
    else:
        file_obj = attachment
        if hasattr(attachment, 'file_name'):
            file_name = attachment.file_name
        else:
            file_name = f"{attachment.file_unique_id}"

    # Use caption as name if provided
    display_name = file_name
    if update.message.caption:
        display_name = update.message.caption

    file = await file_obj.get_file()
    save_path = get_save_path(file_name)
    await file.download_to_drive(save_path)
    
    # Get current folder
    current_folder = user_manager.get_current_folder(update.effective_chat.id)
    
    # Generate Secret Code with ownership and folder
    code = file_manager.save_file_record(str(save_path), update.effective_chat.id, display_name, current_folder)
    
    keyboard = [[InlineKeyboardButton("✏️ Rename", callback_data=f"rename_prompt:{code}")]]
    
    await update.message.reply_text(
        f"File saved to `{current_folder}`! \n\nCode: `{code}`",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Allow register command to pass (though filters handle this, good safety)
    if not is_authorized(update):
        await update.message.reply_text("Please `/register` first.")
        return

    user_id = update.effective_chat.id
    text = update.message.text.strip()
    
    # Check for active state
    state = user_states.get(user_id)
    
    if state == "WAIT_MKDIR":
        if user_manager.create_folder(user_id, text):
            await update.message.reply_text(f"✅ Folder `{text}` created!")
            # Show updated list
            current_folder = user_manager.get_current_folder(user_id)
            reply_markup = get_file_list_markup(user_id, current_folder)
            await update.message.reply_text(f"📂 **Path: {current_folder}**", parse_mode='Markdown', reply_markup=reply_markup)
        else:
            await update.message.reply_text("❌ Failed to create folder (maybe it exists?).")
        
        if user_id in user_states: del user_states[user_id]
        return
        
    elif state == "WAIT_RENAME":
        code = user_context.get(user_id)
        if code and file_manager.rename_file(code, text, user_id):
            await update.message.reply_text(f"✅ File renamed to: {text}")
        else:
            await update.message.reply_text("❌ Failed to rename.")
            
        if user_id in user_states: del user_states[user_id]
        if user_id in user_context: del user_context[user_id]
        return
        
    elif state == "WAIT_SEARCH":
        results = file_manager.search_files(text, user_id)
        if not results:
            await update.message.reply_text(f"🔍 No files found for '{text}'.")
        else:
            message = f"🔍 **Search Results for '{text}':**\n\n"
            for code, name, _ in results:
                message += f"📄 `{code}` - {name}\n"
            await update.message.reply_text(message, parse_mode='Markdown')
            
        if user_id in user_states: del user_states[user_id]
        return
        
    elif state == "WAIT_PASSWORD":
        user_manager.set_web_password(user_id, text)
        await update.message.reply_text(f"✅ Web password set! You can now login at the website with User ID `{user_id}`.")
        if user_id in user_states: del user_states[user_id]
        return

    # Normal text handling (save as text file or retrieve by code)
    file_path_str = file_manager.get_file_path(text)
    
    if file_path_str:
        if os.path.exists(file_path_str):
            # Check if it's a text file we created
            if file_path_str.endswith(".txt"):
                try:
                    with open(file_path_str, "r", encoding="utf-8") as f:
                        content = f.read()
                    await update.message.reply_text(f"📝 **Note/Link** (Code: {text}):\n\n{content}", parse_mode='Markdown')
                except Exception:
                    # Fallback if read fails
                    await update.message.reply_document(document=open(file_path_str, 'rb'), caption=f"Here is your file (Code: {text})")
            else:
                await update.message.reply_document(document=open(file_path_str, 'rb'), caption=f"Here is your file (Code: {text})")
        else:
            await update.message.reply_text("File not found on server.")
    else:
        ensure_download_dir()
        safe_prefix = "".join(c for c in text[:10] if c.isalnum()) or "text"
        file_name = f"{safe_prefix}_{update.message.id}.txt"
        save_path = get_save_path(file_name)
        
        with open(save_path, "w", encoding="utf-8") as f:
            f.write(text)
            
        current_folder = user_manager.get_current_folder(update.effective_chat.id)
        code = file_manager.save_file_record(str(save_path), update.effective_chat.id, f"Note: {safe_prefix}...", current_folder)
        
        keyboard = [[InlineKeyboardButton("✏️ Rename", callback_data=f"rename_prompt:{code}")]]
        
        await update.message.reply_text(
            f"Text saved to `{current_folder}`! \n\nCode: `{code}`",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

async def admin_login(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update): return
    args = context.args
    if len(args) != 1:
        await update.message.reply_text("Usage: `/admin_login <secret_key>`")
        return

    secret = args[0]
    # Hardcoded secret for simplicity as per plan
    if secret == "bharath":
        user_manager.set_admin(update.effective_chat.id, True)
        await update.message.reply_text("👑 You are now an **Admin**! You can access the Admin Panel on the website.")
    else:
        await update.message.reply_text("❌ Invalid secret key.")

async def search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        await update.message.reply_text("Please `/register` first.")
        return

    args = context.args
    if not args:
        await update.message.reply_text("Usage: `/search <query>`")
        return

    query = " ".join(args)
    user_id = update.effective_chat.id
    results = file_manager.search_files(query, user_id)

    if not results:
        await update.message.reply_text(f"🔍 No files found for '{query}'.")
        return

    message = f"🔍 **Search Results for '{query}':**\n\n"
    for code, name, _ in results:
        message += f"📄 `{code}` - {name}\n"
    
    await update.message.reply_text(message, parse_mode='Markdown')

# Deprecated/Legacy commands (kept for compatibility if needed, but flow is now interactive)
async def list_files_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await list_files(update, context)

if __name__ == '__main__':
    token = os.getenv("BOT_TOKEN")
    if not token:
        print("Error: BOT_TOKEN not found in .env file.")
        exit(1)
    
    application = ApplicationBuilder().token(token).build()
    
    application.add_handler(CommandHandler('start', start))
    application.add_handler(CommandHandler('register', register))
    application.add_handler(CommandHandler('list', list_files_command))
    application.add_handler(CommandHandler('admin_login', admin_login))
    application.add_handler(CommandHandler('search', search))
    application.add_handler(CommandHandler('home', home))
    
    # Callback Handler
    application.add_handler(CallbackQueryHandler(button_handler))
    
    application.add_handler(MessageHandler(filters.ATTACHMENT | filters.PHOTO | filters.VIDEO | filters.AUDIO, handle_document))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    
    print("Bot is running...")
    application.run_polling()

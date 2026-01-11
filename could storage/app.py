from flask import Flask, render_template, request, redirect, url_for, session, send_file, jsonify
from user_manager import UserManager
from file_manager import FileManager
import os

app = Flask(__name__)
app.secret_key = 'super_secret_key_change_this'

user_manager = UserManager()
file_manager = FileManager()

@app.route('/')
def index():
    if 'user_id' in session:
        user_id = int(session['user_id'])
        query = request.args.get('q')
        
        if query:
            files = file_manager.search_files(query, user_id)
        else:
            files = file_manager.get_user_files(user_id)
            
        is_admin = user_manager.is_admin(user_id)
        return render_template('index.html', files=files, is_admin=is_admin, query=query)
    return render_template('index.html')

@app.route('/admin')
def admin():
    if 'user_id' not in session:
        return redirect(url_for('index'))
    
    user_id = int(session['user_id'])
    if not user_manager.is_admin(user_id):
        return "Access Denied: Admins only."
        
    query = request.args.get('q')
    if query:
        users = user_manager.search_users(query)
        files = file_manager.search_files(query, None) # None = Admin search
    else:
        users = user_manager.get_all_users()
        files = file_manager.get_all_files()
    
    # Create a mapping of User ID -> Username for display
    # users is a list of (uid, username)
    user_map = {str(uid): username for uid, username in user_manager.get_all_users()}
        
    return render_template('admin.html', users=users, files=files, query=query, user_map=user_map)

@app.route('/api/admin/files')
def api_admin_files():
    if 'user_id' not in session:
        return jsonify({"error": "Unauthorized"}), 401
    
    user_id = int(session['user_id'])
    if not user_manager.is_admin(user_id):
        return jsonify({"error": "Forbidden"}), 403

    files = file_manager.get_all_files()
    user_map = {str(uid): username for uid, username in user_manager.get_all_users()}
    
    data = []
    for code, name, owner in files:
        data.append({
            "code": code,
            "name": name,
            "owner": owner,
            "owner_name": user_map.get(str(owner), "Unknown")
        })
    
    return jsonify(data)

@app.route('/login', methods=['POST'])
def login():
    user_id = request.form.get('user_id')
    password = request.form.get('password')
    
    if user_manager.validate_web_login(user_id, password):
        session['user_id'] = user_id
        return redirect(url_for('index'))
    return "Invalid credentials. <a href='/'>Try again</a>"

@app.route('/logout')
def logout():
    session.pop('user_id', None)
    return redirect(url_for('index'))

@app.route('/upload', methods=['POST'])
def upload():
    if 'user_id' not in session:
        return redirect(url_for('index'))
        
    if 'file' not in request.files:
        return "No file part"
        
    file = request.files['file']
    if file.filename == '':
        return "No selected file"

    if file:
        from utils import ensure_download_dir, get_save_path
        ensure_download_dir()
        
        save_path = get_save_path(file.filename)
        file.save(save_path)
        
        file_manager.save_file_record(str(save_path), int(session['user_id']), file.filename)
        return redirect(url_for('index'))

@app.route('/download/<code>')
def download(code):
    path = file_manager.get_file_path(code)
    if path and os.path.exists(path):
        return send_file(path, as_attachment=True)
    return "File not found"

if __name__ == '__main__':
    app.run(debug=True, port=5001)

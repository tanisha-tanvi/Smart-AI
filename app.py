import os
import sys

# --- PATH FIX FOR CLOUD DEPLOYMENT ---
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

import shutil
import platform
import subprocess
from datetime import datetime

from flask import Flask, request, jsonify, render_template, send_from_directory
from flask_socketio import SocketIO, emit
from dotenv import load_dotenv
import google.generativeai as genai
from werkzeug.utils import secure_filename

# --- DOCUMENT & TRANSLATION IMPORTS ---
import fitz  # PyMuPDF
from docx import Document
from pptx import Presentation
from deep_translator import GoogleTranslator

# --- SAFE INTERNAL SERVICE IMPORTS ---
try:
    from services.storage_service import storage
except Exception as e:
    print(f"❌ Storage Service failed to load: {e}")
    storage = None

try:
    from services.metrics_service import tracker
except:
    tracker = None

try:
    from services import youtube_service, rag_service, file_creator, docker_service
    from services.api_manager import api_manager
except Exception as e:
    print(f"❌ Other services failed to load: {e}")
    api_manager = None

# --- INITIALIZATION & CONFIG ---
load_dotenv()

BASE_WORKSPACE = os.path.abspath("./workspaces")
if not os.path.exists(BASE_WORKSPACE):
    os.makedirs(BASE_WORKSPACE)

SUPPORTED_EXTENSIONS = (
    '.txt', '.py', '.cpp', '.c', '.java', '.js', '.html', '.css', '.md', 
    '.pdf', '.docx', '.pptx', '.jpg', '.jpeg', '.png', '.mp4', '.avi', '.mov'
)

try:
    _supported = GoogleTranslator(source='auto', target='en').get_supported_languages(as_dict=True)
    LANGUAGES = {code: name.title() for name, code in _supported.items()}
except Exception:
    LANGUAGES = {'en': 'English', 'hi': 'Hindi', 'es': 'Spanish', 'fr': 'French'}

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

class UserSession:
    def __init__(self, sid):
        self.sid = sid
        self.content = ""
        self.read_pos = 0
        self.lang = 'en'
        self.vector_store = None
        self.workspace = os.path.join(BASE_WORKSPACE, sid)
        if not os.path.exists(self.workspace):
            os.makedirs(self.workspace)

user_states = {} 
running_processes = {} 

def get_user_state(sid):
    if sid not in user_states:
        user_states[sid] = UserSession(sid)
    return user_states[sid]

# --- GEMINI TOOL SCHEMA ---
tools_schema = [
    {
        "function_declarations": [
            {
                "name": "manage_file",
                "description": "Downloads (opens), reads, or summarizes a local file.",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "filename": {"type": "STRING"},
                        "intent": {"type": "STRING", "enum": ["open", "read", "summarize", "execute", "transcribe"]}
                    },
                    "required": ["filename", "intent"]
                }
            },
            {
                "name": "create_new_file",
                "description": "Creates a new file with AI-generated content.",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "filename": {"type": "STRING"},
                        "prompt": {"type": "STRING"}
                    },
                    "required": ["filename", "prompt"]
                }
            },
            {
                "name": "ask_document",
                "description": "Asks questions about the currently indexed RAG document.",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {"question": {"type": "STRING"}},
                    "required": ["question"]
                }
            }
        ]
    }
]

# --- INTERNAL HELPERS ---

def get_workspace_files(sid):
    """Exclusively scans bucket and local disk. No table needed."""
    files_set = set()
    user = get_user_state(sid)
    
    if os.path.exists(user.workspace):
        for f in os.listdir(user.workspace):
            if os.path.isfile(os.path.join(user.workspace, f)) and f.lower().endswith(SUPPORTED_EXTENSIONS):
                files_set.add(f)
                
    if storage and storage.supabase:
        try:
            # Check sid folder
            res = storage.supabase.storage.from_('workspace-bucket').list(sid)
            if res:
                for item in res:
                    if 'name' in item and item['name'] != '.emptyKeep':
                        files_set.add(item['name'])
            
            # Check root folder (manual uploads)
            root_res = storage.supabase.storage.from_('workspace-bucket').list()
            if root_res:
                for item in root_res:
                    if 'name' in item and item.get('id'): 
                         files_set.add(item['name'])
        except: pass
            
    return sorted(list(files_set))

def upload_to_bucket(sid, filename, local_path):
    if storage and storage.supabase:
        try:
            with open(local_path, 'rb') as f:
                storage.supabase.storage.from_('workspace-bucket').upload(f"{sid}/{filename}", f)
            return True
        except Exception as e:
            if "already exists" in str(e).lower(): return True
    return False

def extract_text(file_path, user):
    ext = os.path.splitext(file_path)[1].lower()
    text = ""
    try:
        if ext in ['.txt', '.py', '.cpp', '.c', '.java', '.js', '.md', '.html', '.css']:
            with open(file_path, 'r', errors='replace') as f: text = f.read()
        elif ext == '.pdf':
            doc = fitz.open(file_path)
            text = "\n".join(page.get_text() for page in doc)
        elif ext == '.docx':
            text = "\n".join([p.text for p in Document(file_path).paragraphs])
        
        if text:
            socketio.emit('terminal_output', {'text': f"[⚙️ Indexing {os.path.basename(file_path)}...]\n"}, room=user.sid)
            user.vector_store = rag_service.build_rag_index(text)
        return text
    except Exception as e:
        return f"Error: {str(e)}"

# --- ROUTES ---

@app.route('/')
def home():
    opts = "".join([f'<option value="{c}" {"selected" if c=="en" else ""}>{n}</option>' 
                   for c, n in LANGUAGES.items()])
    return render_template('index.html', language_options=opts, default_lang='en', file_storage_path=BASE_WORKSPACE)

@app.route('/upload', methods=['POST'])
def handle_upload():
    file = request.files.get('file')
    sid = request.form.get('sid')
    if not file or not sid: return jsonify({"status": "error", "message": "Missing data"}), 400
    
    filename = secure_filename(file.filename)
    user_dir = os.path.join(BASE_WORKSPACE, sid)
    if not os.path.exists(user_dir): os.makedirs(user_dir)
    local_path = os.path.join(user_dir, filename)
    file.save(local_path)

    if upload_to_bucket(sid, filename, local_path):
        return jsonify({"status": "success", "message": f"Uploaded {filename}!"})
    return jsonify({"status": "error", "message": "Bucket sync failed."})

@app.route('/download/<sid>/<filename>')
def download_file(sid, filename):
    user_dir = os.path.join(BASE_WORKSPACE, sid)
    if not os.path.exists(user_dir): os.makedirs(user_dir)
    file_path = os.path.join(user_dir, filename)
    
    if not os.path.exists(file_path) and storage and storage.supabase:
        try:
            res = storage.supabase.storage.from_('workspace-bucket').download(f"{sid}/{filename}")
            with open(file_path, 'wb') as f: f.write(res)
        except:
            try:
                res = storage.supabase.storage.from_('workspace-bucket').download(filename)
                with open(file_path, 'wb') as f: f.write(res)
            except:
                return "Not found in bucket", 404

    return send_from_directory(user_dir, filename, as_attachment=True)

@app.route('/list_files')
def route_list_files():
    sid = request.args.get('sid')
    if not sid: return jsonify({"status": "error", "files": []})
    return jsonify({"status": "success", "files": get_workspace_files(sid)})

@app.route('/command', methods=['POST'])
def process_command():
    data = request.json
    sid = data.get('sid')
    user = get_user_state(sid)
    query = data.get('question', '').strip()
    user.lang = data.get('lang', user.lang)
    target_lang_name = LANGUAGES.get(user.lang, "English")

    if not query: return jsonify({"status": "info", "message": "Ready."})

    # FIX: Don't lowercase the whole query, as filenames are case-sensitive
    parts = query.split(' ', 1)
    action = parts[0].lower()
    
    if action in ['open', 'read', 'run', 'execute', 'summarize', 'transcribe', 'create'] and len(parts) > 1:
        # Get raw filename to preserve case
        raw_filename = parts[1].strip().split()[0]
        filename = secure_filename(raw_filename)
        path = os.path.join(user.workspace, filename)
        
        if action == "open":
            all_files = get_workspace_files(sid)
            # CASE-INSENSITIVE SEARCH
            matched_file = next((f for f in all_files if f.lower() == filename.lower()), None)
            
            if os.path.exists(path) or matched_file:
                final_name = matched_file if matched_file else filename
                return jsonify({
                    "status": "success", "action": "open_url", 
                    "url": f"/download/{sid}/{final_name}", 
                    "message": f"Opening {final_name}..."
                })
            return jsonify({"status": "error", "message": f"File '{filename}' not found."})

        if action == "read":
            if not os.path.exists(path) and storage:
                try:
                    res = storage.supabase.storage.from_('workspace-bucket').download(f"{sid}/{filename}")
                    with open(path, 'wb') as f: f.write(res)
                except: pass
            content = extract_text(path, user)
            user.content = content
            user.read_pos = 0
            return jsonify({"status": "success", "action": "start_read", "message": f"Reading {filename}"})

        if action == "create":
            res = file_creator.create_workspace_file(filename, parts[1], user.workspace, target_lang=target_lang_name)
            if res['status'] == 'success':
                upload_to_bucket(sid, filename, path)
            return jsonify(res)

    if api_manager:
        api_manager.rotate_key()
        model = genai.GenerativeModel('gemini-1.5-flash', tools=tools_schema)
        try:
            response = api_manager.execute_with_retry(model.generate_content, f"Query: {query}")
            is_fc = bool(response.candidates[0].content.parts[0].function_call)
            if is_fc:
                fc = response.candidates[0].content.parts[0].function_call
                args = dict(fc.args)
                if fc.name == "manage_file":
                    return jsonify({"status": "success", "action": "open_url", "url": f"/download/{sid}/{args['filename']}", "message": "Opening..."})
                if fc.name == "create_new_file":
                    res = file_creator.create_workspace_file(args['filename'], args['prompt'], user.workspace, target_lang=target_lang_name)
                    if res['status'] == 'success':
                        upload_to_bucket(sid, args['filename'], os.path.join(user.workspace, args['filename']))
                    return jsonify(res)
            return jsonify({"status": "info", "message": response.text})
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)})
    return jsonify({"status": "error", "message": "System Error."})

@app.route('/read_chunk')
def fetch_chunk():
    sid = request.args.get('sid')
    user = get_user_state(sid)
    if not user or not user.content or user.read_pos >= len(user.content):
        return jsonify({"status": "done"})
    chunk = user.content[user.read_pos : user.read_pos + 600]
    user.read_pos += 600
    return jsonify({"status": "reading", "chunk": chunk})

@app.route('/get_metrics')
def get_metrics():
    return jsonify(tracker.get_report() if tracker else {})

@socketio.on('kill_process')
def handle_kill():
    if request.sid in running_processes:
        running_processes[request.sid].terminate()
        del running_processes[request.sid]
        emit('terminal_output', {'text': "\n[Stopped]\n"})

@socketio.on('connect')
def handle_connect():
    get_user_state(request.sid)

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    socketio.run(app, host='0.0.0.0', port=port, allow_unsafe_werkzeug=True)

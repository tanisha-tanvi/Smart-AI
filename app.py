import os
import sys

# --- PATH FIX FOR CLOUD DEPLOYMENT ---
# Ensures the 'services' folder is found when running via Gunicorn on Render
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

# --- INTERNAL SERVICE IMPORTS ---
try:
    # We import the modules using the relative package structure for stability
    from services.storage_service import storage
    from services.metrics_service import tracker
    from services.api_manager import api_manager
    from services import youtube_service, rag_service, file_creator, docker_service
except ImportError as e:
    print(f"❌ Critical Import Error: {e}")
    # Fallbacks for robustness
    tracker = None
    api_manager = None
    storage = None

# --- INITIALIZATION & CONFIG ---
load_dotenv()

# Base workspace directory (Ephemeral on Render)
BASE_WORKSPACE = os.path.abspath("./workspaces")
if not os.path.exists(BASE_WORKSPACE):
    os.makedirs(BASE_WORKSPACE)

# Supported file extensions for the explorer
SUPPORTED_EXTENSIONS = (
    '.txt', '.py', '.cpp', '.c', '.java', '.js', '.html', '.css', '.md', 
    '.pdf', '.docx', '.pptx', '.jpg', '.jpeg', '.png', '.mp4', '.avi', '.mov'
)

# Initialize Language dictionary
try:
    _supported = GoogleTranslator(source='auto', target='en').get_supported_languages(as_dict=True)
    LANGUAGES = {code: name.title() for name, code in _supported.items()}
except Exception:
    LANGUAGES = {'en': 'English', 'hi': 'Hindi', 'es': 'Spanish', 'fr': 'French'}

app = Flask(__name__)
# Render requires eventlet and cors_allowed_origins="*" for stable web sockets
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

class UserSession:
    """Maintains the isolated state for each unique browser connection."""
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
                "description": "Downloads (opens), reads, or summarizes a local file in the workspace.",
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
                "description": "Creates a new code or text file with AI-generated content.",
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

# --- UTILITIES ---

def extract_text(file_path, user):
    """Parses text and builds RAG index for a specific user session."""
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
    return render_template('index.html', language_options=opts, default_lang='en')

@app.route('/download/<sid>/<filename>')
def download_file(sid, filename):
    """
    Serves files from local workspace. If missing from disk (Render restart),
    it pulls the content from Supabase before serving.
    """
    user_dir = os.path.join(BASE_WORKSPACE, sid)
    if not os.path.exists(user_dir): os.makedirs(user_dir)
    file_path = os.path.join(user_dir, filename)
    
    # Recovery from Supabase if local disk is wiped
    if not os.path.exists(file_path) and storage:
        content = storage.get_file_content(sid, filename)
        if content:
            with open(file_path, 'w', encoding='utf-8') as f: f.write(content)
        else:
            return "File not found", 404

    return send_from_directory(user_dir, filename, as_attachment=True)

@app.route('/list_files')
def get_files():
    """Returns a merged list of local ephemeral files and persistent cloud files."""
    sid = request.args.get('sid')
    if not sid: return jsonify({"status": "error", "files": []})
    
    files_set = set()
    user = get_user_state(sid)
    
    # 1. Check local disk
    if os.path.exists(user.workspace):
        for f in os.listdir(user.workspace):
            if os.path.isfile(os.path.join(user.workspace, f)) and f.lower().endswith(SUPPORTED_EXTENSIONS):
                files_set.add(f)
                
    # 2. Check Supabase
    if storage:
        db_files = storage.get_files(sid)
        for f in db_files: files_set.add(f)
            
    return jsonify({"status": "success", "files": sorted(list(files_set))})

@app.route('/command', methods=['POST'])
def process_command():
    data = request.json
    sid = data.get('sid')
    user = get_user_state(sid)
    query = data.get('question', '').strip()
    user.lang = data.get('lang', user.lang)
    target_lang_name = LANGUAGES.get(user.lang, "English")

    if not query: return jsonify({"status": "info", "message": "Listening..."})

    parts = query.lower().split(' ', 1)
    action = parts[0]
    
    # --- COMMAND INTERCEPTOR ---
    if action in ['open', 'read', 'run', 'execute', 'summarize', 'transcribe', 'create'] and len(parts) > 1:
        filename = secure_filename(parts[1].strip().split()[0])
        path = os.path.join(user.workspace, filename)
        
        if action == "open":
            db_files = storage.get_files(sid) if storage else []
            if os.path.exists(path) or filename in db_files:
                return jsonify({
                    "status": "success", 
                    "action": "open_url", 
                    "url": f"/download/{sid}/{filename}", 
                    "message": f"Sending {filename} to your device..."
                })
            return jsonify({"status": "error", "message": f"File '{filename}' not found."})

        if action == "read":
            # Pull from Cloud if missing locally
            if not os.path.exists(path) and storage:
                content = storage.get_file_content(sid, filename)
                if content:
                    with open(path, 'w', encoding='utf-8') as f: f.write(content)
            
            content = extract_text(path, user)
            user.content = content
            user.read_pos = 0
            return jsonify({"status": "success", "action": "start_read", "message": f"Reading {filename}..."})

        if action == "execute" or action == "run":
            docker_service.execute_code_interactive(path, sid, socketio, running_processes)
            return jsonify({"status": "success", "message": "Initiated execution check."})

        if action == "transcribe":
            socketio.emit('terminal_output', {'text': f"[🎙️ Transcribing {filename}...]\n"}, room=sid)
            res = youtube_service.transcribe_video_file(path, target_lang=user.lang)
            if res['status'] == 'success':
                user.content = res['text_content']
                user.read_pos = 0
                return jsonify({"status": "success", "action": "start_read", "message": res['text_content']})
            return jsonify(res)

        if action == "create":
            res = file_creator.create_workspace_file(filename, parts[1], user.workspace, target_lang=target_lang_name)
            if res['status'] == 'success' and storage:
                with open(path, 'r', encoding='utf-8') as f:
                    storage.save_file(sid, filename, f.read())
            return jsonify(res)

    # --- AI ORCHESTRATION ---
    if api_manager:
        api_manager.rotate_key()
        model = genai.GenerativeModel('gemini-1.5-flash', tools=tools_schema)
        try:
            response = api_manager.execute_with_retry(model.generate_content, f"Query: {query}")
            is_fc = bool(response.candidates[0].content.parts[0].function_call)
            if tracker: tracker.record_routing(is_fc)

            if is_fc:
                fc = response.candidates[0].content.parts[0].function_call
                args = dict(fc.args)
                if fc.name == "manage_file":
                    return jsonify({"status": "success", "action": "open_url", "url": f"/download/{sid}/{args['filename']}", "message": "Opening..."})
                if fc.name == "create_new_file":
                    res = file_creator.create_workspace_file(args['filename'], args['prompt'], user.workspace, target_lang=target_lang_name)
                    if res['status'] == 'success' and storage:
                        with open(os.path.join(user.workspace, args['filename']), 'r', encoding='utf-8') as f:
                            storage.save_file(sid, args['filename'], f.read())
                    return jsonify(res)
                if fc.name == "ask_document":
                    if not user.vector_store: return jsonify({"status": "error", "message": "Please 'read' a file first."})
                    ans = rag_service.query_rag_document(args.get('question', query), user.vector_store)
                    return jsonify({"status": "success", "message": ans})

            return jsonify({"status": "info", "message": response.text})
        except Exception as e:
            return jsonify({"status": "error", "message": f"AI Error: {str(e)}"})
    
    return jsonify({"status": "error", "message": "System not fully initialized."})

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
    if tracker: return jsonify(tracker.get_report())
    return jsonify({})

# --- SOCKET EVENTS ---

@socketio.on('kill_process')
def handle_kill():
    user = get_user_state(request.sid)
    user.content = ""
    if request.sid in running_processes:
        running_processes[request.sid].terminate()
        del running_processes[request.sid]
        emit('terminal_output', {'text': "\n[Process Force Stopped]\n"})

@socketio.on('terminal_input')
def handle_terminal(data):
    if request.sid in running_processes:
        proc = running_processes[request.sid]
        proc.stdin.write((data.get('input', '') + "\n").encode())
        proc.stdin.flush()

@socketio.on('connect')
def handle_connect():
    get_user_state(request.sid)

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    # Note: On Render, use 'gunicorn --worker-class eventlet -w 1 app:app --bind 0.0.0.0:$PORT'
    socketio.run(app, host='0.0.0.0', port=port, allow_unsafe_werkzeug=True)

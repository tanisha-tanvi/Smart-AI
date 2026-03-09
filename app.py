import os
import sys
import threading
from datetime import datetime
from flask import Flask, request, jsonify, render_template
from flask_socketio import SocketIO, emit
from dotenv import load_dotenv
import google.generativeai as genai
import platform
import subprocess
from werkzeug.utils import secure_filename # SECURITY IMPORT

# --- IMPORT MODULES ---
from services import docker_service, youtube_service

# --- DOCUMENT PARSING IMPORTS ---
import fitz # PyMuPDF
from docx import Document
from pptx import Presentation
from deep_translator import GoogleTranslator
from services import rag_service

# --- SETUP ---
load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# 1. SECURITY: Define the Workspace clearly. ALL operations happen here.
WORKSPACE_DIR = os.path.abspath("./workspace")


# Fetch Languages
try:
    _langs = GoogleTranslator(source='auto', target='en').get_supported_languages(as_dict=True)
    LANGUAGES = {code: name.title() for name, code in _langs.items()}
except:
    LANGUAGES = {'en': 'English', 'hi': 'Hindi', 'es': 'Spanish'}

# --- GLOBAL STATE ---
class UserSession:
    def __init__(self):
        self.content = ""
        self.read_pos = 0
        self.lang = 'en'  # Forces English as the default regardless of the list
        self.vector_store = None

user_states = {} 
running_processes = {} 

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# --- TOOL SCHEMA ---
tools_schema = [
    {
        "function_declarations": [
            {
                "name": "manage_file",
                "description": "Opens, reads, or summarizes a local file...",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "filename": {"type": "STRING"},
                        "intent": {"type": "STRING", "enum": ["open", "read", "summarize", "execute"]}
                    },
                    "required": ["filename", "intent"]
                }
            },
            {
                "name": "youtube_assistant",
                "description": "Plays or transcribes YouTube videos.",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "query": {"type": "STRING"},
                        "action": {"type": "STRING", "enum": ["play", "transcribe"]}
                    },
                    "required": ["query", "action"]
                }
            },
            {
                "name": "ask_document",
                "description": "Asks a question about the open file.",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {"question": {"type": "STRING"}},
                    "required": ["question"]
                }
            }
        ]
    }
]

# 2. CONFIGURE GENAI
main_model = None
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
    # CHANGED BACK: You confirmed you have access to 2.5
    main_model = genai.GenerativeModel('gemini-2.5-flash-lite', tools=tools_schema)

# --- CORRECTED SECURE FILE HELPERS ---

def get_real_file_path(filename):
    """
    SECURE VERSION: Only allows access to files inside ./workspace
    """
    safe_name = secure_filename(filename) 
    full_path = os.path.abspath(os.path.join(WORKSPACE_DIR, safe_name))
    
    if not full_path.startswith(WORKSPACE_DIR):
        raise PermissionError(f"SECURITY ALERT: Access denied to {filename}")
        
    if not os.path.exists(full_path):
        # Create empty file if we are trying to write/execute a new script
        # (Optional logic depending on your needs, but sticking to basics for now)
        raise FileNotFoundError(f"File not found: {filename}")
    
    return full_path

def extract_file_content(full_path):
    ext = os.path.splitext(full_path)[1].lower()
    # Added simple safety check
    if ext in ['.txt', '.py', '.cpp', '.c', '.java', '.js', '.html', '.css', '.md']:
        with open(full_path, 'r', errors='replace') as f: return f.read()
    elif ext == '.pdf':
        doc = fitz.open(full_path)
        return "\n".join(page.get_text() for page in doc)
    elif ext == '.docx':
        return "\n".join([p.text for p in Document(full_path).paragraphs])
    return ""

# --- CONTROLLER LOGIC ---


def handle_open_file(filename, intent, sid):
    try:
        full_path = get_real_file_path(filename)
    except (FileNotFoundError, PermissionError) as e:
        return {"status": "error", "message": str(e)}

    # --- 1. LOCAL ACTIONS (NO API KEY USED) ---
    if intent == "open":
        try:
            system_name = platform.system()
            if system_name == 'Windows': os.startfile(full_path)
            elif system_name == 'Darwin': subprocess.call(('open', full_path))
            else: subprocess.call(('xdg-open', full_path))
            return {"status": "success", "message": f"Opened {filename} locally."}
        except Exception as e:
            return {"status": "error", "message": f"Visual Open Error: {e}"}

    if intent == "read":
        content = extract_file_content(full_path)
        if not content:
            return {"status": "error", "message": "This file type cannot be read as text."}
        
        user_states[sid].content = content
        user_states[sid].read_pos = 0
        return {"status": "success", "action": "start_read", "message": f"Reading {filename}..."}

    if intent == "execute":
        docker_service.execute_code_interactive(full_path, sid, socketio, running_processes)
        return {"status": "success", "message": "Starting execution..."}

    # --- 2. AI ACTIONS (SUMMARIZE - REQUIRES API) ---
    if intent == "summarize":
        try:
        # Get the real path (e.g., ./workspace/arjit.mp4)
            full_path = get_real_file_path(filename)
        
            socketio.emit('terminal_output', {'text': f"[🧠 AI Analyzing Media: {filename}...]\n"}, room=sid)
        
        # CALL THE NEW MULTIMODAL SERVICE
            summary = rag_service.summarize_multimodal(full_path)
        
        # Set state so user can 'read' the summary or ask questions
            user_states[sid].content = summary
            user_states[sid].read_pos = 0
        
            return {
                "status": "success", 
                "action": "start_read", 
                "message": f"📝 **VIDEO SUMMARY:**\n\n{summary}"
            }
        except Exception as e:
            return {"status": "error", "message": f"Summarization Failed: {str(e)}"}
    
# --- ROUTES ---
@app.route('/')
def index():
    # Force 'en' to be the selected option in the dropdown
    options = "".join([
        f'<option value="{c}" {"selected" if c=="en" else ""}>{n}</option>' 
        for c, n in LANGUAGES.items()
    ])
    return render_template('index.html', language_options=options, default_lang='en')
# --- REPLACE YOUR EXISTING 'command_handler' WITH THIS ---
# --- REPLACE YOUR EXISTING 'command_handler' WITH THIS ---

@app.route('/command', methods=['POST'])
def command_handler():
    try:
        sid = request.json.get('sid')
        query = request.json.get('question', '').strip()
        if sid not in user_states: user_states[sid] = UserSession()

        parts = query.split(' ', 1)
        cmd_action = parts[0].lower()

        # --- 1. DIRECT LOCAL COMMANDS (NO API KEY CALLS) ---
        # Inside app.py -> command_handler()

# ... existing code ...
        # In app.py inside command_handler()

# Add 'describe' to your list of recognized actions
        if cmd_action in ['open', 'read', 'run', 'execute', 'describe', 'summarize'] and len(parts) > 1:
            filename = parts[1].strip()
    
    # If the user says 'describe' or 'read' on an image, force the 'summarize' intent
            ext = os.path.splitext(filename)[1].lower()
            if ext in ['.jpg', '.jpeg', '.png', '.webp'] and cmd_action in ['describe', 'read']:
                intent = "summarize" 
            else:
                intent = "execute" if cmd_action in ['run', 'execute'] else cmd_action
        
            return jsonify(handle_open_file(filename, intent, sid))

# --- ADD THIS BLOCK HERE ---
        # Inside app.py -> command_handler()

        if cmd_action == 'transcribe' and len(parts) > 1:
            filename = parts[1].strip()
            try:
                full_path = get_real_file_path(filename)
        # Get the target language set by the user in the dropdown
                target_lang = user_states[sid].lang 
        
                socketio.emit('terminal_output', {'text': f"[🎙️ Transcribing & Translating to {target_lang}: {filename}...]\n"}, room=sid)
        
                from services import youtube_service
        # Pass the target_lang here!
                result = youtube_service.transcribe_video_file(full_path, target_lang=target_lang)
        
                if result['status'] == 'success':
                    user_states[sid].content = result['text_content']
                    user_states[sid].read_pos = 0
                    return jsonify({
                        "status": "success", 
                        "action": "start_read", 
                        "message": result['text_content']
                    })
                else:
                    return jsonify({"status": "error", "message": result['message']})
            except Exception as e:
                return jsonify({"status": "error", "message": str(e)})
# ---------------------------
        if cmd_action in ['open', 'read', 'run', 'execute'] and len(parts) > 1:
            filename = parts[1].strip()
            intent = "execute" if cmd_action in ['run', 'execute'] else cmd_action
            return jsonify(handle_open_file(filename, intent, sid))

        # --- 2. MEDIA CONTROLS ---
        if cmd_action in ['pause', 'stop', 'resume', 'continue', 'restart']:
            # ... (keep existing media control logic) ...
            return jsonify({"status": "success", "action": "stop_read", "message": "Action processed."})

        # --- 3. AI COMMANDS (REQUIRES API) ---
        if not main_model: 
            return jsonify({"status": "error", "message": "AI functionality is disabled (No API Key)."})

        # Only now do we call Gemini
        chat = main_model.start_chat(enable_automatic_function_calling=False)
        response = chat.send_message(f"User request: {query}")
        
        if response.parts[0].function_call:
            fc = response.parts[0].function_call
            args = dict(fc.args)
            
            if fc.name == "manage_file":
                # Handle AI-directed file management
                filename = args.get('filename')
                intent = args.get('intent', 'open')
                
                # Smart Intent Fix
                if not args.get('intent'):
                    if 'summarize' in query.lower(): intent = 'summarize'
                    elif 'execute' in query.lower(): intent = 'execute'
                
                return jsonify(handle_open_file(filename, intent, sid))

            # ... (Existing Youtube/Ask Logic) ...
            elif fc.name == "ask_document":
                if not user_states[sid].vector_store:
                     return jsonify({"status": "error", "message": "No document is open."})
                q = args.get('question', query) 
                ans = rag_service.query_rag_document(q, user_states[sid].vector_store)
                return jsonify({"status": "success", "message": ans})

        return jsonify({"status": "info", "message": response.text})

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
    
    
# --- SOCKET IO ---
@socketio.on('terminal_input')
def on_term_input(data):
    sid = request.sid
    if sid in running_processes:
        proc = running_processes[sid]
        if proc.poll() is None:
            proc.stdin.write((data.get('input','') + "\n").encode())
            proc.stdin.flush()

@socketio.on('kill_process')
def on_kill():
    sid = request.sid
    if sid in running_processes:
        running_processes[sid].terminate()
        del running_processes[sid]
        emit('terminal_output', {'text': "\n[Terminated]\n"})
        
# --- PASTE THIS BEFORE THE SOCKETIO SECTION ---

@app.route('/list_files')
def list_files():
    """
    Lists files ONLY in the secure ./workspace directory.
    """
    try:
        # Define allowed extensions
        SUPPORTED_EXTENSIONS = (
            '.txt', '.py', '.cpp', '.c', '.java', '.js', '.html', '.css', '.md', 
            '.pdf', '.docx', '.pptx', 
            '.jpg', '.jpeg', '.png', 
            '.mp4', '.avi', '.mov'
        )

        files = []
        # Folders to ignore
        IGNORED_DIRS = {'.git', 'node_modules', '__pycache__', 'venv', 'env', '.idea', '.vscode'}
        
        # Ensure workspace exists
        if not os.path.exists(WORKSPACE_DIR):
            os.makedirs(WORKSPACE_DIR)

        # Walk through the workspace directory
        for root, dirs, filenames in os.walk(WORKSPACE_DIR):
            # Filter out ignored directories
            dirs[:] = [d for d in dirs if d not in IGNORED_DIRS and not d.startswith('.')]
            
            for filename in filenames:
                if filename.lower().endswith(SUPPORTED_EXTENSIONS):
                    full_path = os.path.join(root, filename)
                    
                    # Get relative path (e.g., "sales.csv" instead of "C:/Users/.../sales.csv")
                    relative_path = os.path.relpath(full_path, WORKSPACE_DIR)
                    
                    # Normalize slashes for Windows
                    files.append(relative_path.replace("\\", "/"))

            # Safety: Don't go too deep (optional)
            depth = root[len(WORKSPACE_DIR):].count(os.sep)
            if depth >= 2: del dirs[:] 

        return jsonify({"status": "success", "files": files})

    except Exception as e:
        print(f"Error listing files: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500
    
# In app.py
@app.route('/read_chunk')
def read_chunk():
    try:
        sid = request.args.get('sid')
        user = user_states.get(sid)
        
        if not user or not user.content or user.read_pos >= len(user.content):
            return jsonify({"status": "done"})
        
        # Grab the next block of text
        chunk = user.content[user.read_pos : user.read_pos+500]
        user.read_pos += 500
        
        # --- UNIVERSAL TRANSLATION BLOCK ---
        # This handles ALL file types (PDF, TXT, Summary, Transcriptions)
        if user.lang and user.lang != 'en':
            try:
                # Translate this specific chunk to the user's selected language
                chunk = GoogleTranslator(source='auto', target=user.lang).translate(chunk)
            except Exception as e:
                print(f"Translation error: {e}")
                
        return jsonify({"status": "reading", "chunk": chunk})

    except Exception as e:
        return jsonify({"status": "done", "message": "Error reading file."})
    
if __name__ == '__main__':
    socketio.run(app, debug=True, allow_unsafe_werkzeug=True)
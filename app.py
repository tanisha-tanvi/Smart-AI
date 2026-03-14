import os
import sys
import threading
import platform
import subprocess
from datetime import datetime

from flask import Flask, request, jsonify, render_template
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
from services import docker_service, youtube_service, rag_service

# --- INITIALIZATION & CONFIG ---
load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
WORKSPACE_DIR = os.path.abspath("./workspace")

if not os.path.exists(WORKSPACE_DIR):
    os.makedirs(WORKSPACE_DIR)

# Global configuration for supported file types
SUPPORTED_EXTENSIONS = (
    '.txt', '.py', '.cpp', '.c', '.java', '.js', '.html', '.css', '.md', 
    '.pdf', '.docx', '.pptx', '.jpg', '.jpeg', '.png', '.mp4', '.avi', '.mov'
)

# Initialize Language dictionary for UI
try:
    _supported = GoogleTranslator(source='auto', target='en').get_supported_languages(as_dict=True)
    LANGUAGES = {code: name.title() for name, code in _supported.items()}
except Exception:
    LANGUAGES = {'en': 'English', 'hi': 'Hindi', 'es': 'Spanish', 'fr': 'French'}

# --- DATA MODELS ---
class UserSession:
    """Maintains the state for each active socket connection."""
    def __init__(self):
        self.content = ""
        self.read_pos = 0
        self.lang = 'en'
        self.vector_store = None
        self.current_file = None

user_states = {} 
running_processes = {} 

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# --- GEMINI TOOL DEFINITIONS ---
tools_schema = [
    {
        "function_declarations": [
            {
                "name": "manage_file",
                "description": "Opens, reads, or summarizes a local file in the workspace.",
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
                "description": "Plays or transcribes YouTube videos for the user.",
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
                "description": "Asks a specific question about the currently opened/indexed document.",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {"question": {"type": "STRING"}},
                    "required": ["question"]
                }
            }
        ]
    }
]

# AI Model initialization
main_model = None
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
    main_model = genai.GenerativeModel('gemini-2.5-flash', tools=tools_schema)

# --- SECURITY & UTILITY HELPERS ---

def get_safe_path(filename):
    """Ensures file operations remain strictly within the workspace directory."""
    safe_name = secure_filename(filename)
    full_path = os.path.abspath(os.path.join(WORKSPACE_DIR, safe_name))
    if not full_path.startswith(WORKSPACE_DIR):
        raise PermissionError(f"Security Violation: Access denied to {filename}")
    return full_path

def extract_text(file_path, sid=None):
    """Parses various document types and triggers RAG indexing automatically."""
    ext = os.path.splitext(file_path)[1].lower()
    text = ""
    try:
        if ext in ['.txt', '.py', '.cpp', '.c', '.java', '.js', '.md', '.html', '.css']:
            with open(file_path, 'r', errors='replace') as f:
                text = f.read()
        elif ext == '.pdf':
            doc = fitz.open(file_path)
            text = "\n".join(page.get_text() for page in doc)
        elif ext == '.docx':
            text = "\n".join([p.text for p in Document(file_path).paragraphs])
        elif ext == '.pptx':
            prs = Presentation(file_path)
            for slide in prs.slides:
                for shape in slide.shapes:
                    if hasattr(shape, "text"): text += shape.text + "\n"
        
        # Build RAG Index in background if text is found
        if text and sid and sid in user_states:
            socketio.emit('terminal_output', {'text': f"[⚙️ Indexing {os.path.basename(file_path)}...]\n"}, room=sid)
            user_states[sid].vector_store = rag_service.build_rag_index(text)
            user_states[sid].current_file = os.path.basename(file_path)
            
        return text
    except Exception as e:
        return f"Extraction Error: {str(e)}"

# --- PRIMARY BUSINESS LOGIC ---

def handle_file_intent(filename, intent, sid):
    """Core logic for handling file-based user requests."""
    try:
        path = get_safe_path(filename)
    except Exception as e:
        return {"status": "error", "message": str(e)}

    # Intent: OPEN (System Level)
    if intent == "open":
        try:
            sys_name = platform.system()
            if sys_name == 'Windows': os.startfile(path)
            else: subprocess.call(('open' if sys_name == 'Darwin' else 'xdg-open', path))
            return {"status": "success", "message": f"Successfully opened {filename} locally."}
        except Exception as e:
            return {"status": "error", "message": f"System Open Error: {e}"}

    # Intent: READ (Parsing & Display)
    if intent == "read":
        content = extract_text(path, sid=sid)
        if not content:
            return {"status": "error", "message": "This file contains no extractable text."}
        user_states[sid].content = content
        user_states[sid].read_pos = 0
        return {"status": "success", "action": "start_read", "message": f"Now reading: {filename}"}

    # Intent: SUMMARIZE (Multimodal AI)
    if intent == "summarize":
        try:
            socketio.emit('terminal_output', {'text': f"[🧠 AI Analyzing {filename}...]\n"}, room=sid)
            summary = rag_service.summarize_multimodal(path)
            user_states[sid].content = summary
            user_states[sid].read_pos = 0
            return {"status": "success", "action": "start_read", "message": summary}
        except Exception as e:
            return {"status": "error", "message": f"AI Summarization Failed: {str(e)}"}

    # Intent: EXECUTE (Code Runner)
    if intent == "execute":
        docker_service.execute_code_interactive(path, sid, socketio, running_processes)
        return {"status": "success", "message": f"Initiated execution of {filename}."}

# --- FLASK WEB ROUTES ---

@app.route('/')
def home():
    """Renders the main dashboard with dynamic language support."""
    opts = "".join([f'<option value="{c}" {"selected" if c=="en" else ""}>{n}</option>' 
                   for c, n in LANGUAGES.items()])
    return render_template('index.html', language_options=opts, default_lang='en')

@app.route('/command', methods=['POST'])
def process_command():
    """Main endpoint for all user text/voice commands."""
    try:
        data = request.json
        sid, query = data.get('sid'), data.get('question', '').strip()
        
        if sid not in user_states:
            user_states[sid] = UserSession()

        # Update session language from request if present
        if 'lang' in data: user_states[sid].lang = data['lang']

        # Parse basic string commands first (CLI style)
        parts = query.split(' ', 1)
        action = parts[0].lower()

        if action in ['open', 'read', 'run', 'execute', 'describe', 'summarize'] and len(parts) > 1:
            file_arg = parts[1].strip()
            ext = os.path.splitext(file_arg)[1].lower()
            
            # Context-aware intent switching
            if ext in ['.jpg', '.png', '.mp4'] and action in ['read', 'describe']:
                intent = "summarize"
            else:
                intent = "execute" if action == "run" else action
            return jsonify(handle_file_intent(file_arg, intent, sid))

        # Handle Transcription commands
        if action == 'transcribe' and len(parts) > 1:
            target = user_states[sid].lang
            path = get_safe_path(parts[1].strip())
            socketio.emit('terminal_output', {'text': f"[🎙️ Transcribing to {target}...]\n"}, room=sid)
            res = youtube_service.transcribe_video_file(path, target_lang=target)
            if res['status'] == 'success':
                user_states[sid].content = res['text_content']
                user_states[sid].read_pos = 0
                return jsonify({"status": "success", "action": "start_read", "message": res['text_content']})
            return jsonify(res)

        # AI Orchestration (Gemini Function Calling)
        if not main_model:
            return jsonify({"status": "error", "message": "Gemini API Key is not configured."})

        chat = main_model.start_chat(enable_automatic_function_calling=True)
        response = chat.send_message(query)
        
        # Check for function call responses
        if response.candidates[0].content.parts[0].function_call:
            fc = response.candidates[0].content.parts[0].function_call
            args = dict(fc.args)

            if fc.name == "manage_file":
                return jsonify(handle_file_intent(args['filename'], args.get('intent', 'open'), sid))
            
            if fc.name == "ask_document":
                if not user_states[sid].vector_store:
                    return jsonify({"status": "error", "message": "No document is indexed for QA."})
                ans = rag_service.query_rag_document(args.get('question', query), user_states[sid].vector_store)
                return jsonify({"status": "success", "message": ans})

        return jsonify({"status": "info", "message": response.text})

    except Exception as e:
        return jsonify({"status": "error", "message": f"Server Error: {str(e)}"}), 500

@app.route('/list_files')
def get_files():
    """Returns a list of all safe files within the workspace."""
    try:
        file_list = []
        for root, _, filenames in os.walk(WORKSPACE_DIR):
            for f in filenames:
                if f.lower().endswith(SUPPORTED_EXTENSIONS):
                    rel = os.path.relpath(os.path.join(root, f), WORKSPACE_DIR)
                    file_list.append(rel.replace("\\", "/"))
        return jsonify({"status": "success", "files": file_list})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route('/read_chunk')
def fetch_text_chunk():
    """Streaming helper for the UI to read content block-by-block with translation."""
    try:
        sid = request.args.get('sid')
        user = user_states.get(sid)
        if not user or not user.content or user.read_pos >= len(user.content):
            return jsonify({"status": "done"})

        chunk = user.content[user.read_pos : user.read_pos + 600]
        user.read_pos += 600

        # On-the-fly translation
        if user.lang != 'en':
            try:
                chunk = GoogleTranslator(source='auto', target=user.lang).translate(chunk)
            except: pass

        return jsonify({"status": "reading", "chunk": chunk})
    except:
        return jsonify({"status": "done"})

# --- SOCKET EVENTS ---

@socketio.on('terminal_input')
def handle_terminal(data):
    """Passes user terminal input to active docker/system processes."""
    sid = request.sid
    if sid in running_processes:
        proc = running_processes[sid]
        if proc.poll() is None:
            proc.stdin.write((data.get('input', '') + "\n").encode())
            proc.stdin.flush()

@socketio.on('kill_process')
def handle_kill():
    """Safely terminates active background processes."""
    sid = request.sid
    if sid in running_processes:
        running_processes[sid].terminate()
        del running_processes[sid]
        emit('terminal_output', {'text': "\n[Process Terminated by User]\n"})

@socketio.on('connect')
def handle_connect():
    """Initializes a new session on connection."""
    user_states[request.sid] = UserSession()

if __name__ == '__main__':
    # allow_unsafe_werkzeug used for local development environments
    socketio.run(app, host='0.0.0.0', port=5000, debug=True, allow_unsafe_werkzeug=True)

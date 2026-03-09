import os
import sys
import subprocess
import threading

def read_process_output(process, sid, socketio, running_processes):
    """Reads stdout/stderr and emits to client."""
    try:
        for line in iter(process.stdout.readline, b''):
            decoded_line = line.decode('utf-8', errors='replace')
            socketio.emit('terminal_output', {'text': decoded_line}, room=sid)
        
        process.stdout.close()
        process.wait()
        socketio.emit('terminal_output', {'text': f"\n[Process finished with exit code {process.returncode}]\n"}, room=sid)
        
        if sid in running_processes:
            del running_processes[sid]
            
    except Exception as e:
        socketio.emit('terminal_output', {'text': f"\n[Error reading output: {str(e)}]\n"}, room=sid)

def execute_code_interactive(full_path, sid, socketio, running_processes):
    """Executes code (Docker for Python, Local for C++/Java)."""
    file_name = os.path.basename(full_path)
    file_extension = os.path.splitext(file_name)[1].lower()
    cmd = []
    cwd = os.path.dirname(full_path)

    # --- DOCKER LOGIC FOR PYTHON ---
    if file_extension == '.py':
        abs_path = os.path.abspath(full_path)
        cmd = [
            'docker', 'run', '--rm', '-i', 
            '-v', f'{abs_path}:/app/{file_name}', 
            '-w', '/app', 'python:3.9-slim', 
            'python', '-u', file_name
        ]
        cwd = None # Docker manages context
        socketio.emit('terminal_output', {'text': f"[🔒 Securing Environment...]\n[🐳 Starting Docker Container...]\n"}, room=sid)

    # --- LOCAL LOGIC FOR C++/JAVA ---
    elif file_extension in ['.c', '.cpp']:
        compiler = 'g++' if file_extension == '.cpp' else 'gcc'
        exe_name = os.path.splitext(full_path)[0]
        if os.name == 'nt': exe_name += ".exe"
        
        socketio.emit('terminal_output', {'text': f"[Compiling {file_name}...]\n"}, room=sid)
        compile_process = subprocess.run([compiler, full_path, '-o', exe_name], capture_output=True, text=True)
        
        if compile_process.returncode != 0:
            socketio.emit('terminal_output', {'text': f"Compilation Failed:\n{compile_process.stderr}\n"}, room=sid)
            return
            
        cmd = [exe_name]
        if os.name != 'nt' and '/' not in exe_name: cmd = ['./' + os.path.basename(exe_name)]

    elif file_extension == '.java':
        cmd = ['java', full_path]

    else:
        socketio.emit('terminal_output', {'text': "Unsupported file type.\n"}, room=sid)
        return

    # Start Process
    try:
        process = subprocess.Popen(
            cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            cwd=cwd, bufsize=0
        )
        running_processes[sid] = process
        
        thread = threading.Thread(target=read_process_output, args=(process, sid, socketio, running_processes))
        thread.daemon = True
        thread.start()
        
        status_msg = f"[Running {file_name} in Sandbox]\n" if file_extension == '.py' else f"[Started {file_name} Locally]\n"
        socketio.emit('terminal_output', {'text': status_msg}, room=sid)

    except Exception as e:
        socketio.emit('terminal_output', {'text': f"Error starting process: {str(e)}\nMake sure Docker is running!"}, room=sid)
import os
import sys
import subprocess
import threading
import docker
from dotenv import load_dotenv

load_dotenv()

def read_process_output(process, log_callback):
    """
    Reads process output and sends it to a callback function 
    instead of emitting via SocketIO.
    """
    try:
        for line in iter(process.stdout.readline, b''):
            decoded_line = line.decode('utf-8', errors='replace')
            # The log_callback is a function passed from app.py 
            # that updates st.session_state.terminal_logs
            log_callback(decoded_line)
        
        process.stdout.close()
        process.wait()
        
        exit_code = process.returncode
        log_callback(f"\n[Process finished with exit code {exit_code}]\n")
            
    except Exception as e:
        log_callback(f"\n[Error reading output: {str(e)}]\n")

def execute_code_interactive(full_path, log_callback):
    """
    Executes code and uses a callback to handle terminal logs.
    """
    file_name = os.path.basename(full_path)
    file_extension = os.path.splitext(file_name)[1].lower()
    cmd = []
    cwd = os.path.dirname(full_path)

    if file_extension == '.py':
        try:
            client = docker.from_env()
            client.ping()
        except Exception:
            log_callback("❌ Docker Error: Daemon not found. Ensure Docker Desktop is running.\n")
            return

        abs_path = os.path.abspath(full_path)
        cmd = [
            'docker', 'run', '--rm', '-i', 
            '-v', f'{abs_path}:/app/{file_name}', 
            '-w', '/app', 'python:3.10-slim', 
            'python', '-u', file_name
        ]
        cwd = None 
        log_callback(f"[🔒 Securing Environment...]\n[🐳 Starting Docker Container (Python 3.10)...]\n")

    elif file_extension in ['.c', '.cpp']:
        compiler = 'g++' if file_extension == '.cpp' else 'gcc'
        exe_name = os.path.splitext(full_path)[0]
        if os.name == 'nt': exe_name += ".exe"
        
        log_callback(f"[Compiling {file_name}...]\n")
        compile_res = subprocess.run([compiler, full_path, '-o', exe_name], capture_output=True, text=True)
        
        if compile_res.returncode != 0:
            log_callback(f"Compilation Failed:\n{compile_res.stderr}\n")
            return
            
        cmd = [exe_name]
        if os.name != 'nt' and '/' not in exe_name: 
            cmd = ['./' + os.path.basename(exe_name)]

    elif file_extension == '.java':
        log_callback(f"[Starting JVM for {file_name}...]\n")
        cmd = ['java', full_path]
    else:
        log_callback(f"Unsupported file type: {file_extension}\n")
        return

    try:
        process = subprocess.Popen(
            cmd, 
            stdin=subprocess.PIPE, 
            stdout=subprocess.PIPE, 
            stderr=subprocess.STDOUT,
            cwd=cwd, 
            bufsize=0
        )
        
        # Start background thread to read output
        thread = threading.Thread(
            target=read_process_output, 
            args=(process, log_callback)
        )
        thread.daemon = True
        thread.start()
        
        return process # Return the process so app.py can manage it (kill/input)

    except Exception as e:
        log_callback(f"Error starting process: {str(e)}\n")
        return None

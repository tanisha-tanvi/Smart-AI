Multimodal AI Voice AssistantNexAssist is an advanced, full-stack AI-driven Voice Assistant and Dynamic Media Assistant designed to bridge the gap between human voice commands and local machine operations. Built with a Python Flask backend and an interactive web frontend, it leverages Gemini 2.5 Flash Lite to analyze, summarize, and interact with various media types including Videos, PDFs, Images, and Code.🌟 Key Features🎙️ Intelligent Voice ControlSpeech-to-Text: Control the entire system using natural voice commands via the Web Speech API.Multilingual TTS: Automatically translates and reads aloud document content, video transcripts, or AI summaries in multiple languages.📂 Multimodal File IntelligenceVideo/Audio Transcription: Transcribes local video files and translates the text into your target language.AI Summarization: Uses Gemini's File API to "watch" videos, "see" images, and "read" documents to provide detailed structural summaries.RAG (Retrieval-Augmented Generation): Chat directly with your local PDFs and documents using FAISS vector indexing.🐳 Secure Code Execution (Sandboxed)Dockerized Python: Runs Python scripts within a secure, isolated Docker container to prevent local system interference.Native C++/Java: Compiles and executes C++ and Java files locally via the interactive terminal.📺 YouTube IntegrationSearch & Play: Instantly find and open YouTube videos through voice or text queries.Direct Transcription: Downloads audio from YouTube links to provide text transcripts for study or reference.🛠️ Technical StackBackend: Flask, Flask-SocketIO (Real-time terminal updates).AI Engine: Google Gemini 2.5 Flash Lite (Multimodal & Function Calling).Document Processing: PyMuPDF (PDF), python-docx (Word), python-pptx (PowerPoint).Media Handling: yt-dlp (YouTube), MoviePy (Video/Audio editing), SpeechRecognition.Security: Docker (Python Sandbox), Werkzeug Secure Filename.Frontend: Tailwind CSS, JavaScript, Socket.io.🚀 Installation & Setup1. PrerequisitesPython 3.9+Docker Desktop (Required for secure Python execution)FFmpeg (Required for audio/video processing)2. Clone and InstallBashgit clone https://github.com/your-username/NexAssist.git
cd NexAssist
pip install -r requirements.txt
3. Environment ConfigurationCreate a .env file in the root directory:Code snippetGEMINI_API_KEY=your_google_gemini_api_key
4. Workspace SetupNexAssist strictly operates within a ./workspace folder for security.Bashmkdir workspace
Place any files you want the AI to analyze (PDFs, Videos, Scripts) into this folder.5. Run the AppBashpython app.py
Open http://127.0.0.1:5000 in your Chrome or Edge browser (for voice support).🖥️ Usage GuideCommandAction"read [filename]"Starts text-to-speech for a document or text file."summarize [filename]"Triggers AI multimodal analysis of a video, image, or doc."run [script.py]"Spawns a Docker container to execute code safely."transcribe [video.mp4]"Extracts audio and provides a written transcript."play [song name]"Searches and opens the most relevant YouTube video.📁 Project Structureapp.py: Main Flask server, socket handling, and AI function routing.services/rag_service.py: Logic for Gemini summarization and FAISS document indexing.services/docker_service.py: Manages the secure execution of code in sandbox environments.services/youtube_service.py: Handles YouTube searching, downloading, and transcription.static/js/main.js: Controls the voice recognition, terminal UI, and TTS playback.
Docker-Compose Configuration for SmartA AI
To simplify the deployment of NexAssist, we can use Docker Compose. This will allow you to run the Flask application, the interactive terminal, and the Python sandbox environment without manually configuring dependencies on your local machine.

1. Create the docker-compose.yml File
Place this file in your root project directory:

YAML
version: '3.8'

services:
  nexassist:
    build: .
    container_name: nexassist_app
    ports:
      - "5000:5000"
    volumes:
      - .:/app
      - ./workspace:/app/workspace
      - /var/run/docker.sock:/var/run/docker.sock # Allows the app to start other containers
    environment:
      - GEMINI_API_KEY=${GEMINI_API_KEY}
    restart: always
    networks:
      - nexassist_net

networks:
  nexassist_net:
    driver: bridge
2. Create a Dockerfile
If you don't have one yet, this file tells Docker how to build your specific environment:

Dockerfile
FROM python:3.9-slim

# Install system dependencies for media and compilation
RUN apt-get update && apt-get install -y \
    ffmpeg \
    g++ \
    default-jdk \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy project files
COPY . .

EXPOSE 5000

CMD ["python", "app.py"]
Why use Docker Compose for this project?
Isolated Workspace: The ./workspace volume ensures that all your PDFs, videos, and scripts stay synchronized between your computer and the container.

Docker-in-Docker: By mounting /var/run/docker.sock, the NexAssist app can still trigger the python:3.9-slim sandbox to run your user scripts safely.

Environment Consistency: It ensures that ffmpeg and your compilers (g++, Java) are always version-matched, regardless of whether you are on Windows or Linux.

How to Launch
Ensure Docker Desktop is running.

Open your terminal in the project folder.

Run the command:
docker-compose up --build

Your assistant will be live at http://localhost:5000.

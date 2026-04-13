/**
 * NexAssist - Main Interaction Logic
 * Supports: Multi-user Sessions, Remote File Transfers, Interactive Terminal, 
 * Voice Recognition (STT), and Speech Synthesis (TTS).
 */

// --- 1. DOM ELEMENT REFERENCES ---
const inputEntry = document.getElementById('input-entry');
const readProgress = document.getElementById('read-progress');
const fileListContainer = document.getElementById('file-list-container');
const langSelect = document.getElementById('lang-select');
const voiceSelect = document.getElementById('voice-select');
const pauseButton = document.getElementById('pause-button');
const resumeButton = document.getElementById('resume-button');
const restartButton = document.getElementById('restart-button');
const rateSlider = document.getElementById('rate-slider');
const currentRateLabel = document.getElementById('current-rate-label');
const terminalInput = document.getElementById('terminal-input');
const outputContainer = document.getElementById('output-container');
const voiceBtn = document.getElementById('voice-button');

// --- 2. SOCKET.IO & SESSION SETUP ---
const socket = io();
let currentSocketId = null;

socket.on('connect', () => { 
    currentSocketId = socket.id; 
    console.log("Connected to NexAssist. Session ID:", currentSocketId);
    listFiles(); // Load workspace for this session immediately
});

// Real-time terminal output from backend (Docker/Transcriptions)
socket.on('terminal_output', (data) => {
    const span = document.createElement('div');
    span.className = "whitespace-pre-wrap font-mono text-xs text-green-400";
    span.innerText = data.text;
    
    if(outputContainer) {
        const inputLine = outputContainer.querySelector('.flex.items-center');
        outputContainer.insertBefore(span, inputLine);
        outputContainer.scrollTop = outputContainer.scrollHeight;
    }
});

// --- 3. GLOBAL STATE ---
let stopRequested = false;
let isReading = false;
let hasContent = false;
let currentRate = 1.0;

// --- 4. COMMAND SUBMISSION (THE CORE LOGIC) ---

async function submitCommand(overrideCommand = null) {
    const commandText = (overrideCommand || inputEntry.value).trim();
    if (!commandText) return;

    stopRequested = false;
    
    // UI Update: Show user command in terminal
    const msg = document.createElement('div');
    msg.className = "mb-2 pb-1 border-b border-slate-800";
    msg.innerHTML = `<span class="text-sky-400 font-bold">You:</span> <span class="text-slate-200">${commandText}</span>`;
    if (outputContainer) {
        outputContainer.insertBefore(msg, outputContainer.querySelector('.flex.items-center'));
        outputContainer.scrollTop = outputContainer.scrollHeight;
    }

    // Reset input if manually typed
    if (!overrideCommand) inputEntry.value = '';

    // Guard: Handle basic stop/pause command locally
    if (commandText.toLowerCase() === 'stop' || commandText.toLowerCase() === 'pause') {
        stopReading();
        return;
    }

    try {
        const response = await fetch('/command', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ 
                question: commandText, 
                sid: currentSocketId,
                lang: langSelect.value
            })
        });

        const data = await response.json();

        if (stopRequested) return;

        /**
         * REMOTE DEVICE FIX:
         * If the server sends an 'open_url', it means the user wants to view a file.
         * Instead of opening it on the server (which fails in cloud), we trigger a 
         * local download on the user's browser (Phone/Laptop).
         */
        if (data.action === 'open_url') {
            const downloadLink = document.createElement('a');
            downloadLink.href = data.url;
            downloadLink.download = ""; 
            document.body.appendChild(downloadLink);
            downloadLink.click();
            document.body.removeChild(downloadLink);
            safeUiUpdate(`System: Initiating file transfer to your device...`, false);
        }

        if (data.action === 'start_read') {
            hasContent = true;
            isReading = true;
            updateControlButtons(true);
            fetchAndSpeakChunk(); 
        } 

        if (data.status === 'success' || data.status === 'info') {
            safeUiUpdate(data.message, false);
            listFiles(); // Refresh explorer in case a file was created
        } else if (data.status === 'error') {
            safeUiUpdate(`Error: ${data.message}`, false);
        }

        // Speak the text response for non-reading tasks
        if (data.action !== 'start_read' && !stopRequested && data.status !== 'error') {
            await speak(data.message);
        }

    } catch (error) {
        console.error("Submission Error:", error);
        safeUiUpdate("Error: Failed to communicate with the AI server.", false);
    }
}

// --- 5. FILE EXPLORER (SUPABASE INTEGRATED) ---

async function listFiles() {
    if (!currentSocketId) return;
    fileListContainer.innerHTML = '<div class="text-center py-6 text-slate-400 text-xs italic">Syncing with cloud workspace...</div>';
    
    try {
        const res = await fetch(`/list_files?sid=${currentSocketId}`);
        const data = await res.json();
        
        if (data.files && data.files.length > 0) {
            // Group files by extension for better UI
            const grouped = data.files.reduce((acc, file) => {
                const ext = file.split('.').pop().toUpperCase();
                const group = ext + ' FILES';
                if (!acc[group]) acc[group] = [];
                acc[group].push(file);
                return acc;
            }, {});

            let html = '';
            for (const groupName in grouped) {
                const files = grouped[groupName];
                const ext = groupName.split(' ')[0].toLowerCase();
                
                const filesHtml = files.map(file => `
                    <div class="flex items-center justify-between p-3 border-b border-slate-100 hover:bg-slate-50 transition">
                        <span class="text-sm text-slate-700 truncate font-medium max-w-[150px]">${file}</span>
                        <div class="flex gap-1">
                            <button onclick="submitCommand('open ${file}')" class="text-[10px] bg-indigo-50 text-indigo-600 px-2 py-1 rounded font-bold border border-indigo-100">Open</button>
                            <button onclick="submitCommand('read ${file}')" class="text-[10px] bg-slate-100 text-slate-600 px-2 py-1 rounded font-bold border border-slate-200">Read</button>
                        </div>
                    </div>
                `).join('');

                html += `
                    <div class="mb-3 bg-white rounded-lg border border-slate-200 overflow-hidden shadow-sm">
                        <div class="px-3 py-2 bg-slate-50 text-[10px] font-bold text-slate-500 uppercase border-b border-slate-200">${groupName}</div>
                        <div>${filesHtml}</div>
                    </div>
                `;
            }
            fileListContainer.innerHTML = html;
        } else {
            fileListContainer.innerHTML = '<div class="text-center py-8 text-slate-400 text-xs italic">Workspace is empty.</div>';
        }
    } catch (e) {
        fileListContainer.innerHTML = '<div class="text-red-400 text-xs p-4">Failed to fetch files from Supabase.</div>';
    }
}

// --- 6. SPEECH & READING LOGIC (TTS) ---

async function fetchAndSpeakChunk() {
    if (!isReading || stopRequested) return;

    try {
        const res = await fetch(`/read_chunk?sid=${currentSocketId}`);
        const data = await res.json();

        if (data.status === 'reading' && !stopRequested) {
            if (readProgress) readProgress.textContent = "🔊 READING...";
            await speak(data.chunk);
            if (isReading && !stopRequested) setTimeout(fetchAndSpeakChunk, 100);
        } else {
            stopReading();
        }
    } catch (e) {
        stopReading();
    }
}

function speak(text) {
    if (stopRequested) return Promise.resolve();
    window.speechSynthesis.cancel();
    
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.lang = langSelect.value;
    utterance.rate = currentRate;
    
    // Find matching voice for the language
    const voices = window.speechSynthesis.getVoices();
    const voice = voices.find(v => v.lang.startsWith(langSelect.value)) || voices[0];
    if (voice) utterance.voice = voice;

    return new Promise(resolve => {
        utterance.onend = resolve;
        utterance.onerror = resolve;
        window.speechSynthesis.speak(utterance);
    });
}

function stopReading() {
    isReading = false;
    window.speechSynthesis.cancel();
    if (readProgress) readProgress.textContent = "PAUSED";
    updateControlButtons(false);
}

// --- 7. VOICE RECOGNITION (STT) ---

function startVoiceCommand() {
    const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!Recognition) {
        safeUiUpdate("System: Voice recognition not supported on this browser.", false);
        return;
    }

    const rec = new Recognition();
    rec.lang = langSelect.value + '-US'; // Basic fallback logic
    
    rec.onstart = () => {
        voiceBtn.textContent = "Listening...";
        voiceBtn.classList.add('bg-red-50', 'text-red-600', 'animate-pulse');
    };

    rec.onresult = (e) => {
        const text = e.results[0][0].transcript;
        inputEntry.value = text;
        submitCommand();
    };

    rec.onend = () => {
        voiceBtn.textContent = "Voice";
        voiceBtn.classList.remove('bg-red-50', 'text-red-600', 'animate-pulse');
    };

    rec.start();
}

// --- 8. UI HELPERS & TERMINAL ---

function safeUiUpdate(text, isFileContent = false) {
    const msg = document.createElement('div');
    msg.className = "mb-2 pb-1 border-b border-slate-800";
    msg.innerHTML = `<span class="text-indigo-400 font-bold">AI:</span> <span class="text-slate-200">${text}</span>`;
    
    if (outputContainer) {
        const inputLine = outputContainer.querySelector('.flex.items-center');
        outputContainer.insertBefore(msg, inputLine);
        outputContainer.scrollTop = outputContainer.scrollHeight;
    }
}

function handleTerminalEnter(event) {
    if (event.key === 'Enter') {
        const val = terminalInput.value;
        if (val.trim()) {
            // Echo input in terminal
            const echo = document.createElement('div');
            echo.className = "font-mono text-xs text-slate-400";
            echo.innerHTML = `<span class="text-green-400">$</span> ${val}`;
            outputContainer.insertBefore(echo, outputContainer.querySelector('.flex.items-center'));
            
            // Send to backend via Socket
            socket.emit('terminal_input', { input: val });
            terminalInput.value = '';
        }
    }
}

function killProcess() {
    stopRequested = true;
    window.speechSynthesis.cancel();
    socket.emit('kill_process');
    safeUiUpdate("System: Global kill signal sent.", false);
}

function updateControlButtons(active) {
    if (pauseButton) pauseButton.disabled = !active;
    if (resumeButton) resumeButton.disabled = !(!active && hasContent);
}

function setReadingRate(val) {
    currentRate = parseFloat(val);
    currentRateLabel.textContent = currentRate.toFixed(1) + 'x';
}

function loadVoices() {
    window.speechSynthesis.getVoices(); // Trigger load
}

// --- 9. METRICS DASHBOARD ---

async function updateMetrics() {
    try {
        const res = await fetch('/get_metrics');
        const data = await res.json();
        document.getElementById('metric-latency').textContent = data.search_latency_ms || 0;
        document.getElementById('metric-routing').textContent = data.routing_reliability || 100;
        document.getElementById('metric-speed').textContent = data.transcription_speed || 0;
        document.getElementById('metric-files').textContent = data.files_processed || 0;
    } catch (e) {}
}
async function performUpload() {
    const fileInput = document.getElementById('file-upload-input');
    const file = fileInput.files[0];
    if (!file) return;

    const formData = new FormData();
    formData.append('file', file);
    formData.append('sid', currentSocketId);

    safeUiUpdate(`System: Uploading ${file.name}...`, false);

    try {
        const response = await fetch('/upload', {
            method: 'POST',
            body: formData
        });
        const data = await response.json();
        
        if (data.status === 'success') {
            safeUiUpdate(data.message, false);
            listFiles(); // Refresh the explorer to show the new file
        } else {
            safeUiUpdate(`Upload Error: ${data.message}`, false);
        }
    } catch (e) {
        safeUiUpdate("System Error: Could not connect to upload service.", false);
    }
}
// --- 10. INITIALIZATION ---

document.addEventListener('DOMContentLoaded', () => {
    setInterval(updateMetrics, 3000);
    window.speechSynthesis.onvoiceschanged = loadVoices;
    
    // Allow Enter key in main input
    inputEntry.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') submitCommand();
    });
});

const inputEntry = document.getElementById('input-entry');
const outputLabel = document.getElementById('output-label');
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

const socket = io();
let currentSocketId = null;

// --- 1. GLOBAL KILL SWITCH STATE ---
// This flag prevents any pending or arriving responses from speaking.
let stopRequested = false;

function killProcess() {
    // 1. Tell backend to terminate any active Docker/Subprocesses
    socket.emit('kill_process');
    
    // 2. Set local flag to ignore incoming voice responses immediately
    stopRequested = true;
    
    // 3. Immediately silence current speech and clear the browser's speech queue
    isReading = false;
    window.speechSynthesis.cancel();
    
    // 4. Update UI to reflect stop
    if (readProgress) readProgress.textContent = "STOPPED";
    updateControlButtons(false);
    
    console.log("🛑 Global stop triggered. Speech silenced and responses blocked.");
}

// --- 2. SYSTEM EFFICIENCY METRICS ---
async function updateEfficiencyMetrics() {
    try {
        const response = await fetch('/get_metrics');
        const data = await response.json();
        
        document.getElementById('metric-latency').textContent = data.search_latency_ms;
        document.getElementById('metric-routing').textContent = data.routing_reliability;
        document.getElementById('metric-speed').textContent = data.transcription_speed;
        document.getElementById('metric-files').textContent = data.files_processed;
        
        const latencyEl = document.getElementById('metric-latency');
        if (data.search_latency_ms > 500) latencyEl.className = 'text-xl font-mono text-rose-400';
        else if (data.search_latency_ms > 200) latencyEl.className = 'text-xl font-mono text-amber-400';
        else latencyEl.className = 'text-xl font-mono text-emerald-400';
    } catch (e) { console.error("Metrics sync error", e); }
}

setInterval(updateEfficiencyMetrics, 3000);

// --- 3. MICROPHONE / SPEECH RECOGNITION ---
let recognition;
let isListening = false;

if ('webkitSpeechRecognition' in window) {
    recognition = new webkitSpeechRecognition();
    recognition.continuous = false;
    recognition.lang = 'en-US';
    recognition.interimResults = false;

    recognition.onstart = function() {
        isListening = true;
        voiceBtn.classList.remove('bg-white', 'text-slate-700');
        voiceBtn.classList.add('bg-rose-500', 'text-white', 'animate-pulse', 'border-rose-600');
        voiceBtn.innerText = "Listening...";
        inputEntry.placeholder = "Listening...";
    };

    recognition.onend = function() {
        isListening = false;
        voiceBtn.classList.remove('bg-rose-500', 'text-white', 'animate-pulse', 'border-rose-600');
        voiceBtn.classList.add('bg-white', 'text-slate-700');
        voiceBtn.innerText = "Voice";
        inputEntry.placeholder = "What would you like to do?";
    };

    recognition.onresult = function(event) {
        const transcript = event.results[0][0].transcript;
        inputEntry.value = transcript;
        safeUiUpdate(`You said: "${transcript}"`, false);
        submitCommand(transcript);
    };

    recognition.onerror = function() { isListening = false; voiceBtn.innerText = "Error"; };
}

function startVoiceCommand() {
    if (!recognition) return;
    isListening ? recognition.stop() : recognition.start();
}

// --- 4. SOCKET IO LOGIC ---
socket.on('connect', () => { currentSocketId = socket.id; });

socket.on('terminal_output', (data) => {
    const span = document.createElement('div');
    span.className = "whitespace-pre-wrap font-mono text-xs text-green-400";
    span.innerText = data.text;
    
    const terminalView = document.getElementById('output-container');
    if(terminalView) {
        const inputLine = terminalView.lastElementChild;
        terminalView.insertBefore(span, inputLine);
        terminalView.scrollTop = terminalView.scrollHeight;
    }
});

function handleTerminalEnter(event) {
    if (event.key === 'Enter') {
        const text = terminalInput.value;
        const echo = document.createElement('div');
        echo.className = "whitespace-pre-wrap font-mono text-xs text-slate-300";
        echo.innerHTML = `<span class="text-green-400">$</span> ${text}`;
        
        const terminalView = document.getElementById('output-container');
        const inputLine = terminalView.lastElementChild;
        terminalView.insertBefore(echo, inputLine);
        
        socket.emit('terminal_input', { input: text });
        terminalInput.value = '';
        terminalView.scrollTop = terminalView.scrollHeight;
    }
}

// --- 5. READING & PLAYBACK ---
let isReading = false;
let hasContent = false;
let selectedVoice = null;
let currentRate = 1.0;

function setReadingRate(rate) {
    currentRate = Math.min(2.0, Math.max(0.5, parseFloat(rate)));
    rateSlider.value = currentRate;
    currentRateLabel.textContent = `${currentRate.toFixed(1)}x`;
}

function safeUiUpdate(text, isFileContent = false) {
    if (!isFileContent) {
        const msg = document.createElement('div');
        msg.className = "mb-2 pb-1 border-b border-slate-800";
        msg.innerHTML = `<span class="text-indigo-400 font-bold">AI:</span> <span class="text-slate-200">${text}</span>`;
        const terminalView = document.getElementById('output-container');
        const inputLine = terminalView.lastElementChild;
        terminalView.insertBefore(msg, inputLine);
        terminalView.scrollTop = terminalView.scrollHeight;
        readProgress.textContent = '';
        updateControlButtons(false);
    }
}

function updateControlButtons(readingActive) {
    pauseButton.disabled = !readingActive;
    restartButton.disabled = !hasContent;
    if (readingActive) {
        pauseButton.textContent = "Pause";
        resumeButton.disabled = true;
        pauseButton.className = "flex-1 py-2 px-3 bg-indigo-100 border border-indigo-200 rounded text-sm font-bold text-indigo-700";
    } else {
        pauseButton.className = "flex-1 py-2 px-3 bg-white border border-slate-200 rounded text-sm font-medium text-slate-600";
        resumeButton.disabled = !(hasContent && !isReading);
        resumeButton.className = resumeButton.disabled ? "flex-1 py-2 px-3 bg-white border border-slate-200 rounded text-sm font-medium text-slate-600 opacity-50" : "flex-1 py-2 px-3 bg-emerald-100 border border-emerald-200 rounded text-sm font-bold text-emerald-700";
    }
}

function speak(text) {
    // GUARD: If stop was requested, do not start any new speech
    if (stopRequested) return Promise.resolve();

    window.speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(text);
    const selectedLangCode = langSelect.value; 
    utterance.lang = selectedLangCode;

    const voices = window.speechSynthesis.getVoices();
    const matchingVoice = voices.find(v => v.lang.startsWith(selectedLangCode));
    if (matchingVoice) utterance.voice = matchingVoice;

    utterance.rate = currentRate;
    return new Promise(resolve => {
        utterance.onend = resolve;
        utterance.onerror = resolve;
        window.speechSynthesis.speak(utterance);
    });
}

function stopReading() {
    isReading = false;
    window.speechSynthesis.cancel();
    if (hasContent && !stopRequested) readProgress.textContent = "PAUSED";
    updateControlButtons(false);
}

function loadVoices() {
    const populateVoiceList = () => {
        const voices = window.speechSynthesis.getVoices();
        voiceSelect.innerHTML = '';
        const targetLangCode = langSelect.value || 'en'; 
        const filteredVoices = voices.filter(voice => voice.lang.startsWith(targetLangCode));
        const voicesToDisplay = filteredVoices.length > 0 ? filteredVoices : voices;
        
        voicesToDisplay.forEach((voice, index) => {
            const option = document.createElement('option');
            option.textContent = `${voice.name} (${voice.lang})`;
            option.value = voice.name;
            if (index === 0) { option.selected = true; selectedVoice = voice; }
            voiceSelect.appendChild(option);
        });
    };
    if ('onvoiceschanged' in window.speechSynthesis) window.speechSynthesis.onvoiceschanged = populateVoiceList;
    populateVoiceList();
}

function setVoice(voiceName) {
    const voices = window.speechSynthesis.getVoices();
    const newVoice = voices.find(v => v.name === voiceName);
    if (newVoice) selectedVoice = newVoice;
}

function setTranslationLanguage() {
    const langName = langSelect.options[langSelect.selectedIndex].text;
    submitCommand(`translate to ${langName}`);
    setTimeout(loadVoices, 100); 
}

// --- 6. BACKEND COMMUNICATION ---
async function submitCommand(overrideCommand = null) {
    const command = (overrideCommand || inputEntry.value).trim().toLowerCase();
    if (!command) return;
    
    // RESET STOP FLAG: Allow speech for the new manual command
    stopRequested = false;
    
    if(!overrideCommand) {
        const msg = document.createElement('div');
        msg.className = "mb-2 pb-1 border-b border-slate-800";
        msg.innerHTML = `<span class="text-sky-400 font-bold">You:</span> <span class="text-slate-200">${command}</span>`;
        const terminalView = document.getElementById('output-container');
        terminalView.insertBefore(msg, terminalView.lastElementChild);
        terminalView.scrollTop = terminalView.scrollHeight;
    }
    
    if (command === 'stop' || command === 'pause') { stopReading(); return; }
    stopReading();

    try {
        const response = await fetch('/command', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ question: command, sid: currentSocketId }) 
        });
        
        const data = await response.json();
        
        // GUARD: If stop was clicked while waiting for the network response, stay silent
        if (stopRequested) return;

        if (data.action === 'start_read') {
            hasContent = true;
            isReading = true;
            updateControlButtons(true);
            fetchAndSpeakChunk(); 
        } 
        else if (data.action === 'file_loaded') {
            hasContent = true;
            updateControlButtons(false);
        }
        else if (data.action === 'open_url') { window.open(data.url, '_blank'); }
        
        safeUiUpdate(data.message, false);
        
        // Only speak the result if a "Stop" hasn't been requested in the meantime
        if (data.action !== 'start_read' && !stopRequested) { 
            await speak(data.message); 
        }
        
        if (data.hasOwnProperty('has_content')) hasContent = data.has_content;
        updateControlButtons(data.action === 'start_read');
        if (!overrideCommand) inputEntry.value = '';

    } catch (error) {
        // Guard against speaking error messages if the user hit stop
        if (stopRequested) return;
        
        safeUiUpdate(`Error: ${error.message}`, false);
        speak("I encountered an error communicating with the server.");
    }
}

async function fetchAndSpeakChunk() {
    // GUARD: Break recursion if stop is requested or reading is toggled off
    if (!isReading || stopRequested) {
        isReading = false;
        return;
    }
    
    try {
        const response = await fetch(`/read_chunk?sid=${currentSocketId}`);
        const data = await response.json();

        if (data.status === 'reading' && !stopRequested) {
            const terminalView = document.getElementById('output-container');
            if (terminalView) {
                const textDiv = document.createElement('div');
                textDiv.className = "mb-2 p-2 bg-slate-800/50 border-l-2 border-indigo-400 rounded-r text-slate-200 text-sm";
                textDiv.innerHTML = `<span class="text-indigo-400 font-bold text-xs uppercase mr-2">[Reading]</span>${data.chunk}`;
                terminalView.insertBefore(textDiv, terminalView.lastElementChild);
                terminalView.scrollTop = terminalView.scrollHeight;
            }

            if (readProgress) readProgress.textContent = "🔊 READING...";
            
            // Speak chunk and wait for it to finish
            await speak(data.chunk);
            
            // Re-check stop flag before scheduling next chunk
            if (isReading && !stopRequested) { 
                setTimeout(fetchAndSpeakChunk, 100); 
            }
        } else {
            stopReading();
        }
    } catch (error) { 
        stopReading(); 
    }
}

// --- 7. UI HELPERS & INITIALIZATION ---
function toggleFolder(folderId, button) {
    const folder = document.getElementById(folderId);
    const icon = button.querySelector('.toggle-icon');
    folder.classList.toggle('hidden');
    icon.textContent = folder.classList.contains('hidden') ? '▼' : '▲';
}

async function listFiles() {
    fileListContainer.innerHTML = '<p class="text-center py-4 text-slate-400 text-sm">Scanning files...</p>';
    try {
        const response = await fetch('/list_files');
        const data = await response.json();
        if (data.status === 'success' && data.files.length > 0) {
            const grouped = data.files.reduce((acc, file) => {
                const ext = file.split('.').pop().toLowerCase();
                const group = ext.toUpperCase() + ' FILES';
                if (!acc[group]) acc[group] = [];
                acc[group].push(file);
                return acc;
            }, {});
            
            let html = '';
            for (const groupName in grouped) {
                const files = grouped[groupName];
                const ext = groupName.split(' ')[0].toLowerCase();
                const isVideo = ext.match(/mp4|mov|avi/i);
                const isCode = ext.match(/py|java|c|cpp|js/i);
                const isImage = ext.match(/jpg|jpeg|png/i);
                let icon = isVideo ? '🎥' : (isCode ? '🧑‍💻' : (isImage ? '🖼️' : '📄'));

                const filesHtml = files.map(file => `
                    <div class="flex flex-col items-start p-3 border-b border-slate-100 hover:bg-white transition group">
                        <div class="flex items-center w-full mb-2 cursor-pointer" onclick="inputEntry.value='open ${file}'; submitCommand();">
                            <span class="mr-2 text-lg">${icon}</span>
                            <span class="text-slate-700 font-medium text-sm w-full truncate">${file}</span>
                        </div>
                        <div class="flex items-center space-x-2 w-full pl-7">
                            <button onclick="inputEntry.value='open ${file}'; submitCommand();" class="text-xs font-medium px-2 py-1 bg-blue-50 text-blue-600 rounded border border-blue-200">Open</button>
                            <button onclick="inputEntry.value='read ${file}'; submitCommand();" class="text-xs font-medium px-2 py-1 bg-emerald-50 text-emerald-600 rounded border border-emerald-200">Read</button>
                            <button onclick="inputEntry.value='summarize ${file}'; submitCommand();" class="text-xs font-medium px-2 py-1 bg-sky-50 text-sky-600 rounded border border-sky-200">Summarize</button>
                        </div>
                    </div>`).join('');
                
                html += `
                    <div class="mb-4 bg-white rounded-lg border border-slate-200 overflow-hidden">
                        <button class="w-full text-left px-4 py-3 bg-slate-50 flex justify-between items-center" onClick="toggleFolder('folder-${ext}', this)">
                            <span class="text-sm font-bold text-slate-600 uppercase">${groupName} (${files.length})</span>
                            <span class="toggle-icon text-slate-400 text-xs">▼</span>
                        </button>
                        <div id="folder-${ext}" class="hidden border-t border-slate-200">${filesHtml}</div>
                    </div>`;
            }
            fileListContainer.innerHTML = html;
        }
    } catch (e) { fileListContainer.innerHTML = `<p class="text-red-500 text-sm p-4">Sync failed.</p>`; }
}

document.addEventListener('DOMContentLoaded', () => {
    langSelect.value = 'en';
    listFiles(); 
    loadVoices(); 
    setReadingRate(1.0);
    updateEfficiencyMetrics();
});
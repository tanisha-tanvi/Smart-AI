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
const voiceBtn = document.getElementById('voice-button'); // Added reference for visual feedback

const socket = io();
let currentSocketId = null;

// --- 1. MICROPHONE / SPEECH RECOGNITION SETUP (NEW) ---
let recognition;
let isListening = false;

if ('webkitSpeechRecognition' in window) {
    recognition = new webkitSpeechRecognition();
    recognition.continuous = false; // Stop after one command
    recognition.lang = 'en-US';
    recognition.interimResults = false;

    recognition.onstart = function() {
        isListening = true;
        // Visual feedback: Turn button Red/Pulse
        voiceBtn.classList.remove('bg-white', 'text-slate-700');
        voiceBtn.classList.add('bg-rose-500', 'text-white', 'animate-pulse', 'border-rose-600');
        voiceBtn.innerText = "Listening...";
        inputEntry.placeholder = "Listening...";
    };

    recognition.onend = function() {
        isListening = false;
        // Reset button style
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

    recognition.onerror = function(event) {
        console.error("Speech error", event);
        isListening = false;
        voiceBtn.innerText = "Error";
    };
} else {
    console.log("Web Speech API not supported in this browser.");
    if(voiceBtn) {
        voiceBtn.disabled = true;
        voiceBtn.innerText = "No Mic";
    }
}

// Function called by HTML button
function startVoiceCommand() {
    if (!recognition) {
        alert("Voice recognition not supported. Use Chrome/Edge.");
        return;
    }
    if (isListening) {
        recognition.stop();
    } else {
        recognition.start();
    }
}

// --- 2. SOCKET IO LOGIC ---

socket.on('connect', () => {
    console.log("Connected to websocket");
    currentSocketId = socket.id;
});

socket.on('terminal_output', (data) => {
    const span = document.createElement('div'); // Changed to div for block display
    span.className = "whitespace-pre-wrap font-mono text-xs text-green-400"; // Matrix style
    span.innerText = data.text;
    
    // Append to terminal output container, not the main chat label
    // Check if we are inside the terminal view
    const terminalView = document.getElementById('output-container');
    if(terminalView) {
        // Insert before the input line
        const inputLine = terminalView.lastElementChild;
        terminalView.insertBefore(span, inputLine);
        terminalView.scrollTop = terminalView.scrollHeight;
    }
});

function handleTerminalEnter(event) {
    if (event.key === 'Enter') {
        const text = terminalInput.value;
        // Visual echo
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

function killProcess() { socket.emit('kill_process'); }

// --- 3. READING & PLAYBACK STATE ---
let isReading = false;
let hasContent = false;
let selectedVoice = null;
let currentRate = 1.0;
let currentContent = "";

function setReadingRate(rate) {
    const newRate = Math.min(2.0, Math.max(0.5, parseFloat(rate)));
    currentRate = newRate;
    rateSlider.value = newRate;
    currentRateLabel.textContent = `${newRate.toFixed(1)}x`;
}

function safeUiUpdate(text, isFileContent = false) {
    if (isFileContent) {
        // For file content, we usually just speak it, but if you want to log it:
        // const span = document.createElement('span');
        // span.className = "text-slate-100 font-sans leading-relaxed block mt-2";
        // span.innerText = text;
        // outputLabel.appendChild(span);
        // outputContainer.scrollTop = outputContainer.scrollHeight;
    } else {
        // Chat / System Messages
        const msg = document.createElement('div');
        msg.className = "mb-2 pb-1 border-b border-slate-800";
        msg.innerHTML = `<span class="text-indigo-400 font-bold">AI:</span> <span class="text-slate-200">${text}</span>`;
        
        // Append to terminal container area (acting as chat log)
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
        pauseButton.className = "flex-1 py-2 px-3 bg-indigo-100 border border-indigo-200 rounded text-sm font-bold text-indigo-700 hover:bg-indigo-200 transition";
    } else {
        pauseButton.className = "flex-1 py-2 px-3 bg-white border border-slate-200 rounded text-sm font-medium text-slate-600 hover:bg-slate-50 transition disabled:opacity-50";
        resumeButton.disabled = !(hasContent && !isReading);
        if (!resumeButton.disabled) {
             resumeButton.className = "flex-1 py-2 px-3 bg-emerald-100 border border-emerald-200 rounded text-sm font-bold text-emerald-700 hover:bg-emerald-200 transition";
        } else {
             resumeButton.className = "flex-1 py-2 px-3 bg-white border border-slate-200 rounded text-sm font-medium text-slate-600 hover:bg-slate-50 transition disabled:opacity-50";
        }
    }
}

// In main.js
function speak(text) {
    window.speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(text);
    
    // Get the language code from your dropdown (e.g., 'de', 'fr', 'nl')
    const selectedLangCode = langSelect.value; 
    utterance.lang = selectedLangCode; // Crucial for correct accent

    // Find a voice on the user's computer that matches that language
    const voices = window.speechSynthesis.getVoices();
    const matchingVoice = voices.find(v => v.lang.startsWith(selectedLangCode));
    
    if (matchingVoice) {
        utterance.voice = matchingVoice;
    }

    utterance.rate = currentRate;
    return new Promise(resolve => {
        utterance.onend = () => resolve();
        utterance.onerror = () => resolve();
        window.speechSynthesis.speak(utterance);
    });
}

function stopReading() {
    isReading = false;
    window.speechSynthesis.cancel();
    if (hasContent) { 
        readProgress.textContent = "PAUSED";
    }
    updateControlButtons(false);
}

function playYouTubeVideo(searchUrl, query) {
    window.open(searchUrl, '_blank');
    safeUiUpdate(`Opening YouTube search for: ${query}`, false);
}

function loadVoices() {
    const populateVoiceList = () => {
        const voices = window.speechSynthesis.getVoices();
        voiceSelect.innerHTML = '';
        
        // Get current selected language (which is now 'en' by default)
        const targetLangCode = langSelect.value || 'en'; 

        // Filter for voices that match 'en'
        const filteredVoices = voices.filter(voice => voice.lang.startsWith(targetLangCode));
        const voicesToDisplay = filteredVoices.length > 0 ? filteredVoices : voices;
        
        voicesToDisplay.forEach((voice, index) => {
            const option = document.createElement('option');
            option.textContent = `${voice.name} (${voice.lang})`;
            option.value = voice.name;
            if (index === 0) {
                option.selected = true;
                selectedVoice = voice; // Set the default voice immediately
            }
            voiceSelect.appendChild(option);
        });
    };
    
    if ('onvoiceschanged' in window.speechSynthesis) {
        window.speechSynthesis.onvoiceschanged = populateVoiceList;
    }
    populateVoiceList();
}

function setVoice(voiceName) {
    const voices = window.speechSynthesis.getVoices();
    const newVoice = voices.find(v => v.name === voiceName);
    if (newVoice) { selectedVoice = newVoice; }
}

function setTranslationLanguage(langCode) {
    const langName = langSelect.options[langSelect.selectedIndex].text;
    submitCommand(`translate to ${langName}`);
    // Reload voices to match new language preference
    setTimeout(loadVoices, 100); 
}

// --- 4. BACKEND COMMUNICATION ---

async function submitCommand(overrideCommand = null) {
    const command = (overrideCommand || inputEntry.value).trim().toLowerCase();
    if (!command) return;
    
    // Add User Message to Chat Log
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
        const responseText = data.message;

        // ... inside submitCommand function ...

        if (data.action === 'start_read') {
    // Set these first so the system knows we are ready
            hasContent = true;
            isReading = true;
            currentContent = data.message; 
    
            updateControlButtons(true);
    // Use the function name that actually exists in your code
            fetchAndSpeakChunk(); 
        } 
        else if (data.action === 'file_loaded') {
            // NEW: Silent Load
            hasContent = true;
            updateControlButtons(false); // Enables "Resume" button so you can click Play later
            // We do NOT call startReading() here
        }
        else if (data.action === 'open_url') {
            // ... rest of your existing logic ...
            window.open(data.url, '_blank');
        } else if (data.action === 'set_rate') {
            setReadingRate(data.rate);
        } else if (data.action === 'stop_read') {
            hasContent = false;
            updateControlButtons(false);
        } else if (data.action === 'execute_interactive') {
            socket.emit('start_execution', { file_path: data.file_path });
            safeUiUpdate(data.message, false);
            return;
        } else if (data.action === 'play_youtube_embedded') {
            window.open(`https://www.youtube.com/watch?v=${data.video_id}`, '_blank');
            safeUiUpdate(`Opening YouTube video: ${data.video_title}`, false);
            await speak(data.message);
            return;
        } else if (data.action === 'play_youtube') {
            playYouTubeVideo(data.url, data.query);
            await speak(data.message);
            return;
        }

        safeUiUpdate(responseText, false);
        
        // Don't speak if it's just a file opening confirmation, 
        // usually the user wants to read the file, not hear "Opening file" then the file immediately.
        if (data.action !== 'start_read') {
             await speak(responseText);
        }
        
        if (data.hasOwnProperty('has_content')) { hasContent = data.has_content; }
        updateControlButtons(data.action === 'start_read');
        if (!overrideCommand) { inputEntry.value = ''; }

    } catch (error) {
        safeUiUpdate(`Error communicating with server: ${error.message}`, false);
        speak("I encountered an error communicating with the server.");
        updateControlButtons(false);
    }
}

async function fetchAndSpeakChunk() {
    if (!isReading) return;
    
    try {
        console.log("Fetching next chunk from server...");
        const response = await fetch(`/read_chunk?sid=${currentSocketId}`);
        const data = await response.json();

        if (data.status === 'reading') {
            console.log("Received chunk:", data.chunk.substring(0, 20) + "...");

            // 1. FIND THE TERMINAL
            const terminalView = document.getElementById('output-container');
            if (terminalView) {
                // 2. CREATE THE TEXT ELEMENT
                const textDiv = document.createElement('div');
                textDiv.className = "mb-2 p-2 bg-slate-800/50 border-l-2 border-indigo-400 rounded-r text-slate-200 font-sans text-sm animate-pulse";
                
                // Show a label and the actual text content
                textDiv.innerHTML = `<span class="text-indigo-400 font-bold text-xs uppercase mr-2">[Reading]</span>${data.chunk}`;
                
                // 3. INSERT BEFORE THE INPUT LINE
                const inputLine = terminalView.lastElementChild;
                terminalView.insertBefore(textDiv, inputLine);
                
                // 4. AUTO-SCROLL TO BOTTOM
                terminalView.scrollTop = terminalView.scrollHeight;
                
                // Remove pulse effect once it starts reading
                setTimeout(() => textDiv.classList.remove('animate-pulse'), 1000);
            }

            // 5. UPDATE PROGRESS LABEL
            if (readProgress) readProgress.textContent = "🔊 READING...";

            // 6. AUDIO PLAYBACK
            await speak(data.chunk);
            
            // 7. CONTINUE LOOP
            if (isReading) { 
                setTimeout(fetchAndSpeakChunk, 100); 
            }
        } else if (data.status === 'done') {
            stopReading();
            safeUiUpdate("--- End of Document ---", false);
        }
    } catch (error) {
        console.error("Critical Read Error:", error);
        stopReading();
    }
}

async function startReading() {
    if (isReading) return;
    
    // Force these to true when the user manually clicks Play/Resume
    isReading = true;
    hasContent = true; 
    
    updateControlButtons(true);
    fetchAndSpeakChunk();
}
// --- 5. UI HELPERS ---

function toggleFolder(folderId, button) {
    const folder = document.getElementById(folderId);
    const icon = button.querySelector('.toggle-icon');
    if (folder.classList.contains('hidden')) {
        folder.classList.remove('hidden');
        icon.textContent = '▲';
    } else {
        folder.classList.add('hidden');
        icon.textContent = '▼';
    }
}

// --- REPLACE YOUR EXISTING listFiles FUNCTION WITH THIS ---

async function listFiles() {
    fileListContainer.innerHTML = '<p class="text-center py-4 text-slate-400 text-sm">Scanning files...</p>';
    try {
        const response = await fetch('/list_files');
        const data = await response.json();
        if (data.status === 'success' && data.files.length > 0) {
            const groupedFiles = data.files.reduce((acc, file) => {
                const fileExtension = file.split('.').pop().toLowerCase();
                const groupName = fileExtension.toUpperCase() + ' FILES';
                if (!acc[groupName]) { acc[groupName] = []; }
                acc[groupName].push(file);
                return acc;
            }, {});
            
            let fileHtml = '';
            for (const groupName in groupedFiles) {
                const fileList = groupedFiles[groupName];
                const fileExtension = groupName.split(' ')[0].toLowerCase();
                const isVideoGroup = fileExtension.match(/mp4|mov|avi|mkv|wmv/i);
                const isCodeGroup = fileExtension.match(/py|java|c|cpp|js|html|css/i);
                const isImageGroup = fileExtension.match(/jpg|jpeg|png|webp/i);
                let groupIcon = isVideoGroup ? '🎥' : (isCodeGroup ? '🧑‍💻' : (isImageGroup ? '🖼️' : '📄'));

                const filesInGroupHtml = fileList.map(file => {
                    const ext = file.split('.').pop().toLowerCase();
                    const isVideo = ['mp4', 'mov', 'avi', 'mkv', 'wmv'].includes(ext);
                    const isImage = ['jpg', 'jpeg', 'png', 'webp'].includes(ext);
                    const isCode = ['py', 'java', 'c', 'cpp'].includes(ext);
                    
                    // Default "Read" button (for TTS)
                    let primaryBtnText = 'Read';
                    let primaryCmd = 'read';
                    let showSummarize = true; 

                    if (isVideo) { primaryBtnText = 'Transcribe'; primaryCmd = 'transcribe'; } 
                    else if (isImage) { primaryBtnText = 'Describe'; primaryCmd = 'read'; showSummarize = false; }

                    // --- 1. NEW OPEN BUTTON (Free/Local) ---
                    let openBtnHtml = `
                        <button onclick="event.stopPropagation(); inputEntry.value='open ${file}'; submitCommand();"
                            class="text-xs font-medium px-2 py-1 bg-blue-50 text-blue-600 rounded border border-blue-200 hover:bg-blue-100 transition">
                            Open
                        </button>`;

                    // --- 2. SUMMARIZE BUTTON (Uses AI Quota) ---
                    let summarizeBtnHtml = '';
                    if (showSummarize) {
                        summarizeBtnHtml = `
                            <button onclick="event.stopPropagation(); inputEntry.value='summarize ${file}'; submitCommand();"
                                class="text-xs font-medium px-2 py-1 bg-sky-50 text-sky-600 rounded border border-sky-200 hover:bg-sky-100 transition">
                                Summarize
                            </button>`;
                    }

                    // --- 3. EXECUTE BUTTON (Docker) ---
                    let executeBtnHtml = '';
                    if (isCode) {
                        executeBtnHtml = `
                            <button onclick="event.stopPropagation(); inputEntry.value='run ${file}'; submitCommand();"
                                class="text-xs font-medium px-2 py-1 bg-purple-50 text-purple-600 rounded border border-purple-200 hover:bg-purple-100 transition">
                                Execute
                            </button>`;
                    }

                    return `
                        <div class="flex flex-col items-start p-3 border-b border-slate-100 last:border-0 hover:bg-white transition group">
                            <div class="flex items-center w-full mb-2 cursor-pointer" onclick="inputEntry.value='open ${file}'; submitCommand();">
                                <span class="mr-2 text-lg">${groupIcon}</span>
                                <span class="text-slate-700 font-medium text-sm w-full truncate" title="${file}">${file}</span>
                            </div>
                            <div class="flex items-center space-x-2 w-full pl-7">
                                ${openBtnHtml}
                                <button onclick="event.stopPropagation(); inputEntry.value='${primaryCmd} ${file}'; submitCommand();"
                                    class="text-xs font-medium px-2 py-1 bg-emerald-50 text-emerald-600 rounded border border-emerald-200 hover:bg-emerald-100 transition">
                                    ${primaryBtnText}
                                </button>
                                ${summarizeBtnHtml}
                                ${executeBtnHtml}
                            </div>
                        </div>
                    `;
                }).join('');
                
                fileHtml += `
                    <div class="mb-4 bg-white rounded-lg border border-slate-200 overflow-hidden">
                        <button class="w-full text-left px-4 py-3 bg-slate-50 hover:bg-slate-100 flex justify-between items-center transition" 
                            onClick="toggleFolder('folder-${fileExtension}', this)">
                            <span class="text-sm font-bold text-slate-600 uppercase tracking-wide">${groupName} (${fileList.length})</span>
                            <span class="toggle-icon text-slate-400 text-xs">▼</span>
                        </button>
                        <div id="folder-${fileExtension}" class="hidden border-t border-slate-200">
                            ${filesInGroupHtml}
                        </div>
                    </div>
                `;
            }
            fileListContainer.innerHTML = fileHtml;
        } else if (data.files.length === 0) {
            fileListContainer.innerHTML = '<p class="text-center text-slate-400 text-sm py-4">No compatible files found in Workspace.</p>';
        } else {
            fileListContainer.innerHTML = `<p class="text-red-500 text-sm p-4">Error: ${data.message}</p>`;
        }
    } catch (error) {
        fileListContainer.innerHTML = `<p class="text-red-500 text-sm p-4">Connection failed: ${error.message}</p>`;
    }
}

document.addEventListener('DOMContentLoaded', async () => {
    // 1. Force the dropdown value to 'en'
    langSelect.value = 'en';
    
    // 2. Refresh the file list
    listFiles(); 
    
    // 3. Load voices and specifically filter for English
    loadVoices(); 
    
    hasContent = false; 
    updateControlButtons(false);
    setReadingRate(currentRate);
});

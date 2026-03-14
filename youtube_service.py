import os
import re
import requests
import urllib.parse
import tempfile
import yt_dlp
import speech_recognition as sr
from deep_translator import GoogleTranslator
from moviepy import VideoFileClip

# Initialize components
recognizer = sr.Recognizer()

# --- HELPER: SEARCH YOUTUBE ---
def search_youtube_simple(query):
    try:
        encoded_query = urllib.parse.quote(query)
        search_url = f"https://www.youtube.com/results?search_query={encoded_query}"
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(search_url, headers=headers, timeout=10)
        
        if response.status_code == 200:
            pattern = r'"videoId":"([a-zA-Z0-9_-]{11})"|/watch\?v=([a-zA-Z0-9_-]{11})'
            matches = re.findall(pattern, response.text)
            if matches:
                for match_tuple in matches:
                    video_id = next((id for id in match_tuple if id), None)
                    if video_id: return video_id
    except Exception as e:
        print(f"YouTube search error: {e}")
    return None

def download_youtube_audio_ytdlp(url, output_path):
    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': output_path,
        'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'wav'}],
        'quiet': True, 'noplaylist': True
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])

def transcribe_audio_file(audio_path, target_lang='en', source_lang='en'):
    """Generic transcription logic used by both YouTube and Local files."""
    try:
        with sr.AudioFile(audio_path) as source:
            audio = recognizer.record(source)   
            transcribed_text = recognizer.recognize_google(audio, language=source_lang)
            
            final_content = transcribed_text
            translation_message = ""
            
            if target_lang != source_lang:
                final_content = GoogleTranslator(source='auto', target=target_lang).translate(transcribed_text)
                translation_message = f" (Translated to {target_lang})"
                
            return {
                "status": "success", "text_content": final_content,
                "target_lang": target_lang, "message": "Transcription complete." + translation_message
            }
    except Exception as e:
        return {"status": "error", "message": f"Transcription error: {e}"}

def transcribe_video_file(full_path, target_lang='en', source_lang='en'):
    """Extracts audio from local video and transcribes."""
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmpfile:
        audio_file_path = tmpfile.name
    
    try:
        clip = VideoFileClip(full_path)
        clip.audio.write_audiofile(audio_file_path, logger=None)
        clip.close()
        return transcribe_audio_file(audio_file_path, target_lang, source_lang)
    except Exception as e:
        return {"status": "error", "message": f"Video processing error: {e}"}
    finally:
        if os.path.exists(audio_file_path): os.remove(audio_file_path)

def handle_youtube_command(command):
    """Routes Youtube commands (play/search)."""
    # Extract query logic (simplified)
    query = command.replace("play", "").replace("search", "").replace("transcribe", "").strip()
    
    # Try video ID
    video_id = search_youtube_simple(query)
    
    if "transcribe" in command and video_id:
         # Note: Transcription logic involves downloading. 
         # For simplicity, we return the Video ID so the client or backend can handle it.
         # The original code had mixed logic. 
         pass

    if video_id:
        return {
            "status": "action", "action": "play_youtube_embedded", 
            "video_id": video_id, "query": query, 
            "message": f"Playing '{query}' on YouTube."
        }
    
    return {"status": "error", "message": "Video not found."}

def transcribe_youtube_video(query, target_lang='en'):
    video_id = search_youtube_simple(query)
    if not video_id: return {"status": "error", "message": "Video not found"}
    
    url = f"https://www.youtube.com/watch?v={video_id}"
    temp_dir = tempfile.gettempdir()
    audio_filename = f"yt_audio_{video_id}.wav"
    downloaded_file = os.path.join(temp_dir, audio_filename)
    
    try:
        download_youtube_audio_ytdlp(url, downloaded_file)
        return transcribe_audio_file(downloaded_file, target_lang=target_lang)
    finally:
         if os.path.exists(downloaded_file): os.remove(downloaded_file)

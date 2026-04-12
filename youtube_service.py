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
    """Searches YouTube for a query and returns the first Video ID found."""
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
    """Downloads audio from a YouTube URL and saves it as a WAV file."""
    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': output_path,
        'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'wav'}],
        'quiet': True, 
        'noplaylist': True
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])

def transcribe_audio_file(audio_path, target_lang='en', source_lang='en'):
    """Generic transcription logic used by both YouTube and Local files."""
    try:
        with sr.AudioFile(audio_path) as source:
            # Adjust for ambient noise to improve accuracy
            recognizer.adjust_for_ambient_noise(source)
            audio = recognizer.record(source)   
            transcribed_text = recognizer.recognize_google(audio, language=source_lang)
            
            final_content = transcribed_text
            translation_message = ""
            
            # Translate if target language is different from source
            if target_lang != source_lang:
                final_content = GoogleTranslator(source='auto', target=target_lang).translate(transcribed_text)
                translation_message = f" (Translated to {target_lang})"
                
            return {
                "status": "success", 
                "text_content": final_content,
                "target_lang": target_lang, 
                "message": "Transcription complete." + translation_message
            }
    except sr.UnknownValueError:
        return {"status": "error", "message": "Google Speech Recognition could not understand the audio."}
    except Exception as e:
        return {"status": "error", "message": f"Transcription error: {e}"}

def transcribe_video_file(full_path, target_lang='en', source_lang='en'):
    """
    Main function for local videos: 
    1. Extracts audio from the video file using moviepy.
    2. Sends the audio to the transcription engine.
    """
    # Create a unique temporary file path
    temp_dir = tempfile.gettempdir()
    audio_file_path = os.path.join(temp_dir, f"temp_audio_{os.getpid()}.wav")
    
    try:
        # Load the video clip and extract the audio track
        clip = VideoFileClip(full_path)
        if clip.audio is None:
            return {"status": "error", "message": "This video file has no audio track."}
            
        # FIX: Removed 'verbose=False' as it's not supported in newer MoviePy versions
        clip.audio.write_audiofile(audio_file_path, codec='pcm_s16le', logger=None)
        clip.close()
        
        # Transcribe the extracted WAV file
        return transcribe_audio_file(audio_file_path, target_lang, source_lang)
    except Exception as e:
        return {"status": "error", "message": f"Local video processing failed: {str(e)}"}
    finally:
        # Cleanup temporary audio file
        if os.path.exists(audio_file_path): 
            try: os.remove(audio_file_path)
            except: pass

def transcribe_youtube_video(query, target_lang='en'):
    """Searches, downloads, and transcribes a YouTube video based on a query."""
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
         if os.path.exists(downloaded_file): 
             try: os.remove(downloaded_file)
             except: pass

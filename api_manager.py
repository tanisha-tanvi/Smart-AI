import os
import itertools
import time
import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()

class APIManager:
    def __init__(self):
        # Parses space-separated keys: "key1 key2 key3"
        keys_str = os.getenv("GEMINI_API_KEYS", "")
        self.keys = keys_str.split()
        
        if not self.keys and os.getenv("GEMINI_API_KEY"):
            self.keys = [os.getenv("GEMINI_API_KEY")]
            
        if not self.keys:
            print("⚠️ WARNING: No Gemini API keys found.")
            
        self.key_pool = itertools.cycle(self.keys)
        self.current_key = None

    def rotate_key(self):
        """Rotates to the next available API key."""
        if not self.keys:
            return None
        self.current_key = next(self.key_pool)
        genai.configure(api_key=self.current_key)
        return self.current_key

    def execute_with_retry(self, func, *args, **kwargs):
        """
        Executes a Gemini function. If a 429 (Quota) error occurs, 
        it rotates the key and retries automatically.
        """
        attempts = 0
        max_attempts = len(self.keys)
        
        while attempts < max_attempts:
            try:
                if not self.current_key: 
                    self.rotate_key()
                return func(*args, **kwargs)
            except Exception as e:
                error_msg = str(e).lower()
                # Catch Quota Exceeded or Service Unavailable
                if "429" in error_msg or "quota" in error_msg or "503" in error_msg:
                    print(f"🔄 Rotating key due to limit...")
                    self.rotate_key()
                    attempts += 1
                    time.sleep(1) 
                    continue
                else:
                    # Raise other errors (like 400 Bad Request) immediately
                    raise e
        raise Exception("All provided API keys have exceeded their current quota.")

api_manager = APIManager()
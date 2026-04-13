import os
from supabase import create_client, Client

class SupabaseStorage:
    def __init__(self):
        # We fetch the keys from Render's Environment
        self.url = os.getenv("SUPABASE_URL")
        self.key = os.getenv("SUPABASE_KEY")
        self.supabase: Client = None
        
        # DEBUG PRINTS: Check Render Logs to see these!
        if not self.url:
            print("❌ DB ERROR: 'SUPABASE_URL' is missing from Render Environment Variables.")
        if not self.key:
            print("❌ DB ERROR: 'SUPABASE_KEY' is missing from Render Environment Variables.")

        if self.url and self.key:
            try:
                # Ensure the URL is clean (no trailing slashes or spaces)
                clean_url = self.url.strip()
                clean_key = self.key.strip()
                
                self.supabase = create_client(clean_url, clean_key)
                print(f"✅ Supabase successfully connected to: {clean_url}")
            except Exception as e:
                print(f"❌ Supabase Connection Failed: {str(e)}")
        else:
            print("⚠️ Supabase client NOT initialized due to missing keys.")

    def save_file(self, sid, filename, content):
        """Saves file meta-data/text to the DB table."""
        if not self.supabase:
            print("❌ Save Failed: Supabase client is None.")
            return False
        try:
            data = {"sid": sid, "filename": filename, "content": content}
            # This 'upsert' works only if you ran the SQL with UNIQUE(sid, filename)
            self.supabase.table("workspaces").upsert(data).execute()
            return True
        except Exception as e:
            print(f"❌ DB Write Error: {e}")
            return False

    def get_files(self, sid):
        if not self.supabase: return []
        try:
            res = self.supabase.table("workspaces").select("filename").eq("sid", sid).execute()
            return [item['filename'] for item in res.data]
        except Exception as e:
            print(f"❌ DB List Error: {e}")
            return []

    def get_file_content(self, sid, filename):
        if not self.supabase: return None
        try:
            res = self.supabase.table("workspaces").select("content").eq("sid", sid).eq("filename", filename).execute()
            return res.data[0]['content'] if res.data else None
        except Exception as e:
            print(f"❌ DB Read Error: {e}")
            return None

storage = SupabaseStorage()

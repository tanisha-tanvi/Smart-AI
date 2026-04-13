import os
from supabase import create_client, Client

class SupabaseStorage:
    def __init__(self):
        self.url = os.getenv("SUPABASE_URL")
        self.key = os.getenv("SUPABASE_KEY")
        self.supabase: Client = None
        
        if self.url and self.key:
            try:
                self.supabase = create_client(self.url, self.key)
                print("✅ Supabase Connected")
            except Exception as e:
                print(f"❌ Supabase Error: {e}")

    def save_file(self, sid, filename, content):
        """Saves file meta-data/text to the DB table."""
        if not self.supabase: return False
        try:
            data = {"sid": sid, "filename": filename, "content": content}
            self.supabase.table("workspaces").upsert(data).execute()
            return True
        except: return False

    def get_files(self, sid):
        """Lists files from the database."""
        if not self.supabase: return []
        try:
            res = self.supabase.table("workspaces").select("filename").eq("sid", sid).execute()
            return [item['filename'] for item in res.data]
        except: return []

    def get_file_content(self, sid, filename):
        """Gets text content from the database."""
        if not self.supabase: return None
        try:
            res = self.supabase.table("workspaces").select("content").eq("sid", sid).eq("filename", filename).execute()
            return res.data[0]['content'] if res.data else None
        except: return None

storage = SupabaseStorage()

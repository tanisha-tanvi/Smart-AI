import os
from supabase import create_client, Client

class SupabaseStorage:
    def __init__(self):
        # These come from your Render Environment Variables
        self.url = os.getenv("SUPABASE_URL")
        self.key = os.getenv("SUPABASE_KEY")
        self.supabase: Client = None
        
        if self.url and self.key:
            try:
                self.supabase = create_client(self.url, self.key)
                print("✅ Supabase Storage Connected")
            except Exception as e:
                print(f"❌ Supabase Connection Error: {e}")
        else:
            print("⚠️ Supabase Credentials missing. Files will be temporary.")

    def save_file(self, sid, filename, content):
        """Saves or updates a file in the Supabase 'workspaces' table."""
        if not self.supabase:
            return False
        try:
            # Upsert handles both creating new files and updating existing ones
            data = {
                "sid": sid,
                "filename": filename,
                "content": content
            }
            # This relies on the UNIQUE(sid, filename) constraint we added in SQL
            self.supabase.table("workspaces").upsert(data).execute()
            return True
        except Exception as e:
            print(f"❌ Supabase Save Error: {e}")
            return False

    def get_files(self, sid):
        """Fetches all filenames belonging to a specific session ID."""
        if not self.supabase:
            return []
        try:
            response = self.supabase.table("workspaces").select("filename").eq("sid", sid).execute()
            return [item['filename'] for item in response.data]
        except Exception as e:
            print(f"❌ Supabase List Error: {e}")
            return []

    def get_file_content(self, sid, filename):
        """Retrieves the text content of a specific file for reading/downloading."""
        if not self.supabase:
            return None
        try:
            response = self.supabase.table("workspaces").select("content").eq("sid", sid).eq("filename", filename).execute()
            if response.data and len(response.data) > 0:
                return response.data[0]['content']
            return None
        except Exception as e:
            print(f"❌ Supabase Read Error: {e}")
            return None

    def delete_file(self, sid, filename):
        """Permanently removes a file from the cloud workspace."""
        if not self.supabase:
            return False
        try:
            self.supabase.table("workspaces").delete().eq("sid", sid).eq("filename", filename).execute()
            return True
        except Exception as e:
            print(f"❌ Supabase Delete Error: {e}")
            return False

# Initialize the global storage instance
storage = SupabaseStorage()

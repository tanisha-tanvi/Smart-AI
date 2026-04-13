import os
import firebase_admin
from firebase_admin import credentials, firestore
from google.cloud.firestore_v1.base_query import FieldFilter

class CloudStorage:
    def __init__(self):
        self.db = None
        self.app_id = os.getenv("APP_ID", "nex-assist-default")
        self.init_firebase()

    def init_firebase(self):
        """Initializes Firebase Admin SDK using environment variables."""
        try:
            # We look for a service account JSON string in env
            # Or use the default credentials if running in a supported environment
            if not firebase_admin._apps:
                cred_path = os.getenv("FIREBASE_SERVICE_ACCOUNT_JSON")
                if cred_path and os.path.exists(cred_path):
                    cred = credentials.Certificate(cred_path)
                    firebase_admin.initialize_app(cred)
                else:
                    # Fallback for environments where auth is pre-configured
                    firebase_admin.initialize_app()
            self.db = firestore.client()
        except Exception as e:
            print(f"⚠️ Firebase Init Warning: {e}. Falling back to local disk (non-persistent).")

    def get_user_collection(self, sid):
        """Rule 1: Strict Paths /artifacts/{appId}/public/data/workspaces"""
        if not self.db: return None
        return self.db.collection('artifacts').document(self.app_id).collection('public').document('data').collection('workspaces').document(sid).collection('files')

    def save_file(self, sid, filename, content, file_type='text'):
        """Saves file content to the cloud."""
        if not self.db: return False
        try:
            col = self.get_user_collection(sid)
            col.document(filename).set({
                'name': filename,
                'content': content,
                'type': file_type,
                'updated_at': firestore.SERVER_TIMESTAMP
            })
            return True
        except Exception as e:
            print(f"Error saving to cloud: {e}")
            return False

    def get_files(self, sid):
        """Rule 2: Simple Queries. Fetches all files for a user."""
        if not self.db: return []
        try:
            col = self.get_user_collection(sid)
            docs = col.stream()
            return [doc.to_dict() for doc in docs]
        except Exception as e:
            print(f"Error fetching files: {e}")
            return []

    def get_file_content(self, sid, filename):
        """Fetches a single file's content."""
        if not self.db: return None
        try:
            col = self.get_user_collection(sid)
            doc = col.document(filename).get()
            return doc.to_dict() if doc.exists else None
        except Exception as e:
            print(f"Error reading file: {e}")
            return None

storage = CloudStorage()

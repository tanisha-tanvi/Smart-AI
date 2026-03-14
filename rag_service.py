import os
import time
import faiss
import numpy as np
from PIL import Image
from PyPDF2 import PdfReader
from dotenv import load_dotenv
import google.generativeai as genai

load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

# Use dedicated models for embeddings and generation
EMBED_MODEL = "models/embedding-001"
CHAT_MODEL = genai.GenerativeModel('gemini-2.5-flash')

# --- Multimodal Summarization (Direct Gemini SDK) ---

def summarize_multimodal(file_path):
    """Summarizes Text, PDF, Video, Audio, or Images using Gemini's File API."""
    print(f"🚀 AI Uploading: {file_path}")
    
    # 1. Upload to Gemini File API
    myfile = genai.upload_file(path=file_path)
    
    # 2. Handle processing states (Required for video/audio)
    while myfile.state.name == "PROCESSING":
        print("⏳ Waiting for processing...")
        time.sleep(3)
        myfile = genai.get_file(myfile.name)

    if myfile.state.name == "FAILED":
        raise ValueError("AI failed to process the file.")

    # 3. Generate summary
    response = CHAT_MODEL.generate_content([
        myfile, 
        "\n\nTask: Provide a detailed summary. Describe visual events for video, "
        "details for images, or key points for documents."
    ])
    return response.text

# --- Framework-Free RAG Implementation ---

class VectorStore:
    """A lightweight FAISS wrapper to replace LangChain vector stores."""
    def __init__(self):
        self.index = None
        self.chunks = []

    def add_texts(self, texts):
        self.chunks = texts
        # Generate embeddings directly via Google SDK
        result = genai.embed_content(
            model=EMBED_MODEL,
            content=texts,
            task_type="retrieval_document"
        )
        embeddings = np.array(result['embedding']).astype('float32')
        
        # Initialize and build FAISS index
        dimension = embeddings.shape[1]
        self.index = faiss.IndexFlatL2(dimension)
        self.index.add(embeddings)

    def similarity_search(self, query, k=3):
        # Embed the query
        query_embedding = genai.embed_content(
            model=EMBED_MODEL,
            content=query,
            task_type="retrieval_query"
        )['embedding']
        
        # Search index
        distances, indices = self.index.search(np.array([query_embedding]).astype('float32'), k)
        return [self.chunks[i] for i in indices[0]]

def build_rag_index(text_content):
    """Creates a vector store index from text content."""
    if not text_content:
        return None
    
    # Split text into chunks manually
    chunk_size = 1000
    chunks = [text_content[i:i + chunk_size] for i in range(0, len(text_content), 800)]
    
    v_store = VectorStore()
    v_store.add_texts(chunks)
    return v_store

def query_rag_document(query, vector_store):
    """Queries the framework-free vector store and generates an answer."""
    if not vector_store:
        return "No document is currently indexed."

    # Retrieve context
    relevant_chunks = vector_store.similarity_search(query, k=3)
    context = "\n".join(relevant_chunks)
    
    # Generate response with provided context
    prompt = f"""
    Answer the question as detailed as possible from the provided context.
    If the answer is not in the context, say "answer is not available in the context".
    
    Context:
    {context}
    
    Question: 
    {query}
    """
    response = CHAT_MODEL.generate_content(prompt)
    return response.text

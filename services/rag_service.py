import os
import time
import faiss
import numpy as np
import google.generativeai as genai

# Relative imports for metrics and API management
from .metrics_service import tracker
from .api_manager import api_manager

# Using the most stable model for compatibility across all API keys
# 'models/embedding-001' is the most widely supported name in Google AI Studio
EMBED_MODEL = "models/gemini-embedding-001"
CHAT_MODEL_NAME = 'gemini-2.5-flash'

# --- Multimodal Summarization (Direct Gemini SDK) ---

def summarize_multimodal(file_path, target_lang='English'):
    """Summarizes media or PDFs using rotated API keys with automatic retry."""
    
    # 1. Upload to Gemini File API with retry logic
    # The execute_with_retry helper handles rotation if Key A hits a quota limit
    print(f"🚀 AI Uploading: {os.path.basename(file_path)}")
    myfile = api_manager.execute_with_retry(genai.upload_file, path=file_path)
    
    # 2. Handle processing states for media files (video/audio)
    while myfile.state.name == "PROCESSING":
        time.sleep(2)
        myfile = genai.get_file(myfile.name)

    if myfile.state.name == "FAILED":
        raise ValueError("AI failed to process the file.")

    # 3. Generate summary in the specific target language
    model = genai.GenerativeModel(CHAT_MODEL_NAME)
    
    # Wrap the content generation in our retry logic to ensure silent key-switching
    response = api_manager.execute_with_retry(
        model.generate_content,
        [
            myfile, 
            f"Provide a detailed summary WRITTEN ENTIRELY IN {target_lang}. "
            "Describe visual events for video, technical details for images, or key points for documents. "
            f"Ensure high fidelity to the source content."
        ]
    )
    return response.text

# --- Framework-Free RAG Implementation ---

class VectorStore:
    """A lightweight FAISS wrapper for local vector search with API rotation."""
    def __init__(self):
        self.index = None
        self.chunks = []

    def add_texts(self, texts):
        """Generates embeddings and builds the FAISS index."""
        self.chunks = texts
        
        try:
            # Generate embeddings using the retry wrapper to handle quota limits
            result = api_manager.execute_with_retry(
                genai.embed_content,
                model=EMBED_MODEL,
                content=texts,
                task_type="retrieval_document"
            )
            
            # Convert the result list to a float32 numpy array for FAISS
            embeddings = np.array(result['embedding']).astype('float32')
            
            # Build FAISS index based on embedding dimensions
            dimension = embeddings.shape[1]
            self.index = faiss.IndexFlatL2(dimension)
            self.index.add(embeddings)
            return True
        except Exception as e:
            print(f"❌ Indexing Error during embedding: {e}")
            return False

    def similarity_search(self, query, k=3):
        """Finds most relevant chunks and records search latency."""
        if not self.index:
            return []

        # Start precision timing for the Efficiency Dashboard
        start_time = time.perf_counter()
        
        try:
            # Embed the query using the retry wrapper
            result = api_manager.execute_with_retry(
                genai.embed_content,
                model=EMBED_MODEL,
                content=query,
                task_type="retrieval_query"
            )
            query_embedding = result['embedding']
            
            # Search the local index for the top k nearest neighbors
            distances, indices = self.index.search(np.array([query_embedding]).astype('float32'), k)
            
            # Record total search latency in the metrics tracker
            tracker.record_search(time.perf_counter() - start_time)
            
            return [self.chunks[i] for i in indices[0]]
        except Exception as e:
            print(f"❌ Search Error during retrieval: {e}")
            return []

def build_rag_index(text_content):
    """Creates a local FAISS vector store index from raw text strings."""
    if not text_content:
        return None
    
    # Split text into chunks (approx 1000 chars with 200 char overlap)
    chunk_size = 1000
    chunks = [text_content[i:i + chunk_size] for i in range(0, len(text_content), 800)]
    
    v_store = VectorStore()
    if v_store.add_texts(chunks):
        # Successfully indexed: update the dashboard doc count
        tracker.record_indexing()
        return v_store
    return None

def query_rag_document(query, vector_store):
    """Retrieves context and generates a grounded, language-aware answer."""
    if not vector_store:
        return "No document is currently indexed."

    # Step 1: Retrieve context chunks
    relevant_chunks = vector_store.similarity_search(query, k=3)
    if not relevant_chunks:
        return "The system is currently busy or failed to find relevant data in the document."

    context = "\n".join(relevant_chunks)
    
    # Step 2: Generate Answer using retrieved context
    prompt = f"""
    Answer the following question as detailed as possible using the provided context.
    If the answer is not contained within the context, state that the information is unavailable.
    
    Context:
    {context}
    
    Question and Language Instruction: 
    {query}
    
    Response Policy:
    1. Only use the provided context.
    2. Respond in the specific language requested in the instruction.
    3. Be precise and professional.
    """
    
    model = genai.GenerativeModel(CHAT_MODEL_NAME)
    
    # Final generation protected by the rotation retry logic
    response = api_manager.execute_with_retry(
        model.generate_content,
        prompt
    )
    return response.text

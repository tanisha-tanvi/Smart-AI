import os
import google.generativeai as genai
from PIL import Image
from langchain_google_genai import GoogleGenerativeAIEmbeddings, ChatGoogleGenerativeAI
from langchain_community.vectorstores import FAISS
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain.chains.question_answering import load_qa_chain
from langchain.prompts import PromptTemplate
from dotenv import load_dotenv

load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
import time
import google.generativeai as genai

def summarize_multimodal(file_path):
    """
    Summarizes Text, PDF, Video, Audio, or Images using Gemini's File API.
    """
    print(f"🚀 AI Uploading: {file_path}")
    
    # 1. Upload file to Gemini File API
    # This is necessary for videos/audio to be 'watched' by the AI
    myfile = genai.upload_file(path=file_path)
    
    # 2. Wait for processing (Crucial for Video)
    # Gemini needs a few seconds to 'index' the video frames
    while myfile.state.name == "PROCESSING":
        print("⏳ Waiting for video processing...")
        time.sleep(3)
        myfile = genai.get_file(myfile.name)

    if myfile.state.name == "FAILED":
        raise ValueError("AI failed to process the video file.")

    # 3. Use the 2.5-flash-lite model to summarize
    model = genai.GenerativeModel('gemini-2.5-flash-lite')
    
    response = model.generate_content([
        myfile, 
        "\n\nTask: Provide a detailed summary of this file. "
        "If it's a video, explain the visual events and any audio/speech. "
        "If it's an image, describe it. If it's a document, list key points."
    ])

    return response.text

# Configure GenAI for summarization tasks
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

def summarize_content_with_gemini(text_content):
    """Summarizes text content using Gemini."""
    if not GEMINI_API_KEY:
        return "Error: GEMINI_API_KEY not found."
    
    try:
        model = genai.GenerativeModel('gemini-2.5-flash-lite')
        prompt = f"""
        You are a helpful assistant. Please provide a concise but comprehensive 
        summary of the following content. 
        
        - If it is code, explain what it does.
        - If it is a transcript, summarize the main discussion points.
        
        Content:
        {text_content[:30000]} 
        """
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        return f"Gemini Summarization Error: {str(e)}"

# In services/rag_service.py

def summarize_image_with_gemini(full_path):
    """Analyzes an image file and returns a text description."""
    if not GEMINI_API_KEY:
        return {"status": "error", "message": "GEMINI_API_KEY not found."}

    try:
        model = genai.GenerativeModel('gemini-2.5-flash-lite')
        img = Image.open(full_path)
        # We use a 'describe' style prompt here
        prompt = "Describe this image in detail. Mention objects, colors, and the overall context."
        
        response = model.generate_content([prompt, img])

        return {
            "status": "success", 
            "text_content": response.text,
            "message": "Image description complete."
        }
    except Exception as e:
        return {"status": "error", "message": f"Gemini Vision Error: {str(e)}"}

def build_rag_index(text_content):
    """Creates a FAISS Vector Store from text."""
    if not text_content or not GEMINI_API_KEY: 
        return None
    
    try:
        text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)
        chunks = text_splitter.split_text(text_content)
        
        embeddings = GoogleGenerativeAIEmbeddings(model="models/embedding-001", google_api_key=GEMINI_API_KEY)
        vector_store = FAISS.from_texts(chunks, embedding=embeddings)
        return vector_store
    except Exception as e:
        print(f"RAG Build Error: {e}")
        return None

def query_rag_document(query, vector_store):
    """Queries the vector store."""
    if not vector_store:
        return "No document is currently indexed."

    try:
        docs = vector_store.similarity_search(query, k=3)
        llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash-lite", google_api_key=GEMINI_API_KEY, temperature=0.3)
        
        prompt_template = """
        Answer the question as detailed as possible from the provided context.
        If the answer is not in the context, just say "answer is not available in the context".
        
        Context:
        {context}
        
        Question: 
        {question}
        
        Answer:
        """
        prompt = PromptTemplate(template=prompt_template, input_variables=["context", "question"])
        chain = load_qa_chain(llm, chain_type="stuff", prompt=prompt)
        response = chain({"input_documents": docs, "question": query}, return_only_outputs=True)
        return response["output_text"]
    except Exception as e:
        return f"RAG Query Error: {e}"

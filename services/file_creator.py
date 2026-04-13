import os
from docx import Document
import google.generativeai as genai
from .api_manager import api_manager

# Ensure we save to the correct workspace directory
WORKSPACE_DIR = os.path.abspath("./workspace")

def generate_ai_content(prompt, filename, target_lang='English'):
    """
    Uses Gemini to generate the specific body content for a new file.
    It identifies whether code or text is needed based on the filename extension.
    """
    ext = os.path.splitext(filename)[1].lower()
    
    # Contextual instruction for the AI
    if ext in ['.py', '.java', '.cpp', '.c', '.js', '.html', '.css']:
        format_type = "source code"
        additional_instr = "Provide ONLY the raw code. Do not include markdown formatting (no backticks ```)."
    elif ext == '.docx':
        format_type = "a detailed passage/essay"
        additional_instr = "Write in a professional format suitable for a Word document."
    else:
        format_type = "plain text content"
        additional_instr = ""

    system_prompt = f"""
    You are an automated file generator. Your goal is to write {format_type} for a file named '{filename}'.
    The language of the content must be {target_lang}.
    {additional_instr}
    
    Topic/Requirement: {prompt}
    """

    # Use the rotated model and retry logic
    model = genai.GenerativeModel('gemini-2.5-flash')
    response = api_manager.execute_with_retry(
        model.generate_content,
        system_prompt
    )
    
    return response.text.strip()

def create_workspace_file(filename, prompt, target_lang='English'):
    """
    Primary function to generate content and write it to the physical file.
    Handles specialized formats like .docx differently than standard text.
    """
    try:
        # 1. Generate the content using AI
        content = generate_ai_content(prompt, filename, target_lang)
        
        # 2. Define the absolute path
        file_path = os.path.join(WORKSPACE_DIR, filename)
        ext = os.path.splitext(filename)[1].lower()

        # 3. Handle File Creation logic
        if ext == '.docx':
            doc = Document()
            # Split by double newlines to create proper paragraphs in Word
            paragraphs = content.split('\n\n')
            for p in paragraphs:
                if p.strip():
                    doc.add_paragraph(p.strip())
            doc.save(file_path)
        else:
            # Handle text-based files (.txt, .py, .java, .cpp, .md, etc.)
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content)
        
        return {
            "status": "success", 
            "message": f"Successfully created '{filename}' in the workspace based on your request."
        }
    except Exception as e:
        return {
            "status": "error", 
            "message": f"File Creation Failed: {str(e)}"
        }

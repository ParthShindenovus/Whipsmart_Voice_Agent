import os
from dotenv import load_dotenv
from google import genai


load_dotenv(override=True)

# Initialize the client globally
client = genai.Client(api_key=os.environ["GOOGLE_API_KEY"])

def get_rag_content():
    """Get the RAG content from the file."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    rag_content_path = os.path.join(script_dir, "assets", "knowledgebase_formatted.txt")
    with open(rag_content_path, "r") as f:
        return f.read()


RAG_MODEL = "gemini-2.0-flash-lite-preview-02-05"
RAG_CONTENT = get_rag_content()
RAG_PROMPT = f"""
You are a helpful assistant designed to answer user questions based solely on the provided knowledge base.

**Instructions:**

1.  **Knowledge Base Only:** Answer questions *exclusively* using the information in the "Knowledge Base" section below. Do not use any outside information.
2.  **Conversation History:** Use the "Conversation History" (ordered oldest to newest) to understand the context of the current question.
3.  **Concise Response:**  Respond in 50 words or fewer.  The response will be spoken, so avoid symbols, abbreviations, or complex formatting. Use plain, natural language.
4.  **Unknown Answer:** If the answer is not found within the "Knowledge Base," respond with "I don't know." Do not guess or make up an answer.
5. Do not introduce your response. Just provide the answer.
6. You must follow all instructions.

**Input Format:**

Each request will include:

*   **Conversation History:**  (A list of previous user and assistant messages, if any)

**Knowledge Base:**
Here is the knowledge base you have access to:
{RAG_CONTENT}
"""


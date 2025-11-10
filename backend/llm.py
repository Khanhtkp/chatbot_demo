from google import genai
import os

client = genai.Client(api_key = "API_KEY")

def ask_llm(question, snippets):
    context = "\n\n---\n\n".join(snippets)
    prompt = f"""You are a codebase assistant.
Below are code snippets from the project. Use them to answer user questions accurately.

{context}

Question: {question}
Answer in detail:"""
    response = client.models.generate_content(
        model="gemini-2.5-flash", contents=prompt
)
    return response.text

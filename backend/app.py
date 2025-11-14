from fastapi import FastAPI, Request
from pydantic import BaseModel
from indexer import ensure_index, retrieve_context
from llm import ask_llm
from fastapi.middleware.cors import CORSMiddleware
from probing import construct_retrieval_query
import os
import logging
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
class ChatRequest(BaseModel):
    question: str
    parent_root: str
class IndexRequest(BaseModel):
    parent_root: str
@app.post("/index")
async def index_folder(req: IndexRequest):
    ensure_index(req.parent_root)
    return {"status": "ok"}
@app.post("/chat")
def chat(req: ChatRequest):
    ensure_index(req.parent_root)

    # Find a code file to probe (simplify: pick currently edited or last modified file)
    candidate_file = find_recent_code_file(req.parent_root)
    if candidate_file:
        logging.info(f"📄 Candidate file opened: {candidate_file}")
        with open(candidate_file, "r", encoding="utf-8") as f:
            code_text = f.read()
        retrieval_query = construct_retrieval_query(req.question, code_text)
        logging.info(f"Query: {retrieval_query}")
    else:
        logging.info("⚠️ No candidate file found.")
        retrieval_query = req.question

    # 🔸 Use the constructed retrieval query for context retrieval
    retrieved = retrieve_context(req.parent_root, retrieval_query, top_k=8)
    logging.info(f"Documents retrieved: {retrieved}")
    # Ask the LLM with the *user question* + retrieved context
    answer = ask_llm(req.question, retrieved)
    return {"answer": answer, "context": retrieved}


def find_recent_code_file(root_dir: str):
    """Pick the most recently modified code file in the workspace."""
    exts = (".py", ".js", ".ts", ".cpp", ".java", ".cs", ".ipynb")
    latest = None
    latest_mtime = -1
    for dirpath, _, filenames in os.walk(root_dir):
        for f in filenames:
            if f.endswith(exts):
                fp = os.path.join(dirpath, f)
                mtime = os.path.getmtime(fp)
                if mtime > latest_mtime:
                    latest = fp
                    latest_mtime = mtime
    return latest

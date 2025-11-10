from fastapi import FastAPI, Request
from pydantic import BaseModel
from indexer import ensure_index, retrieve_context
from llm import ask_llm
from fastapi.middleware.cors import CORSMiddleware

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
    retrieved = retrieve_context(req.parent_root, req.question, top_k=8)
    answer = ask_llm(req.question, retrieved)
    return {"answer": answer, "context": retrieved}

import os
import json
import hashlib
import time
import logging
from pathlib import Path
import numpy as np
import faiss
import ast
import torch
from transformers import AutoTokenizer, AutoModel
from rank_bm25 import BM25Okapi
import re
# ================================
# Configuration
# ================================
INDEX_DIR = "storage"
TEXT_EXTENSIONS = {".py", ".js", ".ts", ".java", ".cpp", ".cs", ".txt", ".md", ".ipynb", ".toml", ".yaml"}
MODEL_NAME = "jinaai/jina-embeddings-v2-base-code"  # Code-aware embedding model

# Load Jina model properly (no partial weights issue)
tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
model = AutoModel.from_pretrained(MODEL_NAME, trust_remote_code=True).to("cuda").eval()

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# ================================
# Utilities
# ================================
def hash_text(text: str):
    """SHA256 hash for incremental change detection."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_json(path, default=None):
    if os.path.exists(path):
        with open(path, "r") as f:
            return json.load(f)
    return default if default is not None else []


def save_json(obj, path):
    with open(path, "w") as f:
        json.dump(obj, f, indent=2)

def tokenize_code(text):
    return re.findall(r"\w+", text)
# ================================
# Embedding Function
# ================================
def encode_texts(texts, batch_size=16):
    """Encode texts using Jina embedding model."""
    all_embeddings = []

    for i in range(0, len(texts), batch_size):
        batch = texts[i:i + batch_size]
        inputs = tokenizer(batch, padding=True, truncation=True, return_tensors="pt").to("cuda")

        with torch.no_grad():
            outputs = model(**inputs)
            # Jina models output pooled embeddings directly
            if hasattr(outputs, "pooler_output"):
                emb = outputs.pooler_output
            elif isinstance(outputs, torch.Tensor):
                emb = outputs
            else:
                emb = outputs[0]

            emb = torch.nn.functional.normalize(emb, p=2, dim=1)
            all_embeddings.append(emb.cpu().numpy().astype("float32"))

    return np.vstack(all_embeddings)


# ================================
# Code Chunking (AST-based)
# ================================
def extract_code_chunks(path):
    """Extracts functions, classes, and top-level code blocks from a Python file."""
    text = Path(path).read_text(errors="ignore")
    ext = Path(path).suffix.lower()

    if ext != ".py":
        return [{"type": "file", "name": Path(path).name, "code": text[:3000]}]

    try:
        tree = ast.parse(text)
        chunks = []
        lines = text.splitlines()
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                start = node.lineno - 1
                end = getattr(node, "end_lineno", start + 1)
                snippet = "\n".join(lines[start:end])
                chunks.append({
                    "type": node.__class__.__name__,
                    "name": getattr(node, "name", ""),
                    "code": snippet
                })
        if not chunks:
            chunks = [{"type": "file", "name": Path(path).name, "code": text[:3000]}]
        return chunks
    except Exception as e:
        logging.warning(f"AST parse failed for {path}: {e}")
        return [{"type": "file", "name": Path(path).name, "code": text[:3000]}]


# ================================
# Indexing
# ================================
def ensure_index(root_dir: str):
    os.makedirs(INDEX_DIR, exist_ok=True)
    index_path = f"{INDEX_DIR}/{Path(root_dir).stem}.faiss"
    docs_json_path = f"{INDEX_DIR}/docs.json"
    emb_cache_path = f"{INDEX_DIR}/embeddings.npy"

    existing_docs = load_json(docs_json_path, [])
    existing_docs_dict = {d["uid"]: d for d in existing_docs}

    new_docs = []

    logging.info(f"📦 Scanning directory: {root_dir}")
    for p in Path(root_dir).rglob("*.*"):
        if not (p.is_file() and p.suffix.lower() in TEXT_EXTENSIONS):
            continue
        if any(x in str(p) for x in [".git", "__pycache__"]):
            continue

        chunks = extract_code_chunks(p)
        for c in chunks:
            snippet = c["code"].strip()
            if not snippet:
                continue
            snippet_hash = hash_text(snippet[:3000])
            uid = f"{p.resolve()}::{c['name']}"
            old_hash = existing_docs_dict.get(uid, {}).get("hash")

            if old_hash != snippet_hash:
                new_docs.append({
                    "uid": uid,
                    "path": str(p.resolve()),
                    "name": c["name"],
                    "type": c["type"],
                    "text": snippet[:3000],
                    "hash": snippet_hash
                })
                logging.info(f"   ➕ Updated: {uid}")

    if not new_docs:
        logging.info("✅ No new or updated code chunks found.")
        return

    # Merge metadata
    for d in new_docs:
        existing_docs_dict[d["uid"]] = d
    all_docs = list(existing_docs_dict.values())
    save_json(all_docs, docs_json_path)

    # Embed new docs only
    texts = [d["text"] for d in new_docs]
    t0 = time.time()
    new_emb = encode_texts(texts)
    logging.info(f"🧠 Embedded {len(texts)} new chunks in {time.time() - t0:.2f}s")

    # Update FAISS index
    if os.path.exists(index_path) and os.path.exists(emb_cache_path):
        index = faiss.read_index(index_path)
        old_emb = np.load(emb_cache_path)
        all_emb = np.concatenate([old_emb, new_emb], axis=0)
    else:
        index = faiss.IndexFlatIP(new_emb.shape[1])
        all_emb = new_emb

    index.add(new_emb)
    np.save(emb_cache_path, all_emb)
    faiss.write_index(index, index_path)
    logging.info(f"✅ FAISS index updated ({len(all_emb)} vectors).")

    # Build BM25
    tokenized = [d["text"].split() for d in all_docs]
    tokenized = [tokenize_code(d["text"]) for d in all_docs]
    bm25 = BM25Okapi(tokenized)
    save_json({"docs": all_docs}, f"{INDEX_DIR}/bm25.json")
    logging.info("✅ BM25 index refreshed.")


# ================================
# Retrieval (Hybrid)
# ================================
def retrieve_context(root_dir, query, top_k=8, alpha=0.7):
    """Hybrid dense + lexical retrieval"""
    docs = load_json(f"{INDEX_DIR}/docs.json")
    if not docs:
        raise ValueError("No indexed documents found. Run ensure_index() first.")

    index_path = f"{INDEX_DIR}/{Path(root_dir).stem}.faiss"
    emb_cache_path = f"{INDEX_DIR}/embeddings.npy"

    if not os.path.exists(index_path) or not os.path.exists(emb_cache_path):
        raise ValueError("Missing FAISS or embedding cache.")

    # Dense
    emb = encode_texts([query])
    index = faiss.read_index(index_path)
    dense_scores, dense_idx = index.search(emb, top_k * 2)

    # Lexical (BM25)
    bm25_data = load_json(f"{INDEX_DIR}/bm25.json")
    tokenized = [d["text"].split() for d in bm25_data["docs"]]
    bm25 = BM25Okapi(tokenized)
    query_tokens = query.replace("\n", " ").split()  # simple, same as indexing
    bm25_scores = bm25.get_scores(query_tokens)
    logging.info(f"Dense scores: {dense_scores[0][:10]}")
    logging.info(f"Dense idx: {dense_idx[0][:10]}")
    logging.info(f"BM25 max: {bm25_scores.max()} | BM25 nonzero: {(bm25_scores > 0).sum()}")
    # Fusion
    combined = {}
    for i, doc_idx in enumerate(dense_idx[0]):
        if doc_idx < len(docs):
            max_bm25 = bm25_scores.max() if bm25_scores.max() > 0 else 1.0
            combined[doc_idx] = alpha * dense_scores[0][i] + (1 - alpha) * (bm25_scores[doc_idx] / max_bm25)

    top_results = sorted(combined.items(), key=lambda x: x[1], reverse=True)[:top_k]
    return [docs[i]["text"][:1000] for i, _ in top_results]

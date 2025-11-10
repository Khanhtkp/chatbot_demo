import os
import json
import hashlib
import time
from pathlib import Path
import numpy as np
import faiss
from sentence_transformers import SentenceTransformer
from rank_bm25 import BM25Okapi
import logging

# ================================
# Configuration
# ================================
INDEX_DIR = "storage"
TEXT_EXTENSIONS = {".py", ".js", ".ts", ".java", ".cpp", ".cs", ".txt", ".md", ".ipynb"}

# ✅ Use a lighter model for speed (same E5 family)
# Replace with "intfloat/e5-mistral-7b-instruct" if you want maximum quality
model = SentenceTransformer("intfloat/e5-mistral-7b-instruct", device="cuda")

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)


# ================================
# Utilities
# ================================
def hash_text(text: str):
    """Fast SHA256 hash for change detection."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_json(path, default=None):
    """Load JSON safely."""
    if os.path.exists(path):
        with open(path, "r") as f:
            return json.load(f)
    return default if default is not None else []


def save_json(obj, path):
    """Save JSON with nice formatting."""
    with open(path, "w") as f:
        json.dump(obj, f, indent=2)


# ================================
# Indexing Function
# ================================
def ensure_index(root_dir: str):
    os.makedirs(INDEX_DIR, exist_ok=True)
    index_path = f"{INDEX_DIR}/{Path(root_dir).stem}.faiss"
    docs_json_path = f"{INDEX_DIR}/docs.json"
    emb_cache_path = f"{INDEX_DIR}/embeddings.npy"

    logging.info(f"📂 Indexing folder (incremental): {root_dir}")

    existing_docs = load_json(docs_json_path, [])
    existing_docs_dict = {str(Path(d['path']).resolve()): d for d in existing_docs}

    # --------------------------
    # Step 1: Detect new/updated files
    # --------------------------
    new_or_updated_docs = []
    for p in Path(root_dir).rglob("*.*"):
        if not (p.is_file() and p.suffix.lower() in TEXT_EXTENSIONS):
            continue
        if any(x in str(p) for x in [".git", "__pycache__"]):
            continue

        p_resolved = str(p.resolve())
        try:
            txt = p.read_text(errors="ignore").strip()
            if not txt:
                continue

            txt_hash = hash_text(txt[:3000])
            old_hash = existing_docs_dict.get(p_resolved, {}).get("hash")

            if old_hash != txt_hash:
                new_or_updated_docs.append({
                    "path": p_resolved,
                    "text": txt[:3000],
                    "hash": txt_hash
                })
                logging.info(f"   ➕ Updated file: {p_resolved}")

        except Exception as e:
            logging.warning(f"   ⚠️ Could not read {p_resolved}: {e}")

    if not new_or_updated_docs:
        logging.info("✅ No new or updated documents detected")
        return

    # --------------------------
    # Step 2: Merge & update metadata
    # --------------------------
    for doc in new_or_updated_docs:
        existing_docs_dict[doc['path']] = doc
    all_docs = list(existing_docs_dict.values())
    save_json(all_docs, docs_json_path)

    # --------------------------
    # Step 3: Embed new docs only
    # --------------------------
    t0 = time.time()
    new_texts = [d["text"] for d in new_or_updated_docs]
    new_emb = model.encode(
        new_texts,
        batch_size=16,
        normalize_embeddings=True,
        convert_to_numpy=True,
        show_progress_bar=True
    ).astype('float32')
    logging.info(f"🧠 Encoded {len(new_texts)} new/updated docs in {time.time()-t0:.2f}s")

    # --------------------------
    # Step 4: Incrementally update FAISS
    # --------------------------
    if os.path.exists(index_path) and os.path.exists(emb_cache_path):
        index = faiss.read_index(index_path)
        old_emb = np.load(emb_cache_path)
        new_all_emb = np.concatenate([old_emb, new_emb], axis=0)
    else:
        dim = new_emb.shape[1]
        index = faiss.IndexFlatIP(dim)
        new_all_emb = new_emb

    index.add(new_emb)
    np.save(emb_cache_path, new_all_emb)
    faiss.write_index(index, index_path)
    logging.info(f"✅ FAISS index updated with {len(new_all_emb)} total embeddings")

    # --------------------------
    # Step 5: Rebuild BM25 (lightweight)
    # --------------------------
    tokenized = [d["text"].split() for d in all_docs]
    bm25 = BM25Okapi(tokenized)
    bm25_cache_path = f"{INDEX_DIR}/bm25.json"
    save_json({"docs": all_docs}, bm25_cache_path)
    logging.info("✅ BM25 index updated")


# ================================
# Retrieval Function
# ================================
def retrieve_context(root_dir, query, top_k=8):
    docs = load_json(f"{INDEX_DIR}/docs.json")
    index_path = f"{INDEX_DIR}/{Path(root_dir).stem}.faiss"

    if not docs or not os.path.exists(index_path):
        raise ValueError("❌ No FAISS index or docs found. Run ensure_index() first.")

    emb = model.encode([query], normalize_embeddings=True, convert_to_numpy=True)
    index = faiss.read_index(index_path)
    _, idx = index.search(emb.astype('float32'), top_k)
    return [docs[i]["text"][:1000] for i in idx[0] if i < len(docs)]
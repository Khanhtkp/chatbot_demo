# probing.py
from transformers import AutoTokenizer, AutoModelForSeq2SeqLM
import torch

# Load once at startup
model_id = "Salesforce/codet5p-220m"
tokenizer = AutoTokenizer.from_pretrained(model_id)

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
model = AutoModelForSeq2SeqLM.from_pretrained(model_id).to(device)
model.eval()

def construct_retrieval_query(user_question: str, code_text: str, f: int = 10, m: int = 10, g: int = 10):
    """
    Build retrieval query via log-probability-guided probing (Algorithm 1)
    """
    lines = code_text.splitlines()
    chunks = ["\n".join(lines[i:i+f]) for i in range(0, len(lines), f)]
    if not chunks:
        return code_text

    # Treat the last chunk as target (simplification)
    target_chunk = chunks[-1]

    scores = []
    for i, ci in enumerate(chunks[:-1]):
        probe = ci + "\n" + target_chunk
        inputs = tokenizer(probe, return_tensors="pt", truncation=True, max_length=512).to(device)
        with torch.no_grad():
            outputs = model(**inputs, labels=inputs["input_ids"])
            # loss is average negative log-likelihood per token, so multiply by length for total log-prob
            log_probs = -outputs.loss.item() * inputs["input_ids"].size(1)
        scores.append((i, log_probs))

    # Pick top-g chunks
    top_chunks = sorted(scores, key=lambda x: x[1], reverse=True)[:g]
    top_code = "\n".join([chunks[i] for i, _ in top_chunks])
    retrieval_query = top_code + "\n" + target_chunk
    return retrieval_query

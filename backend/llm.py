import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

# Load the tokenizer
model_name = "TIGER-Lab/AceCoder-Qwen2.5-Coder-7B-Ins-RM"
tokenizer = AutoTokenizer.from_pretrained(model_name)

# Load the model in quantized mode (4-bit or 8-bit)
model = AutoModelForCausalLM.from_pretrained(
    model_name,
    device_map="auto",
    load_in_4bit=True,           # set to True for 4-bit quantization
    torch_dtype=torch.float16     # internal computation can stay in fp16
)

def ask_llm(question, snippets):
    # Combine snippets as context
    context = "\n\n---\n\n".join(snippets)
    prompt = f"""You are a codebase assistant.
Below are code snippets from the project. Use them to answer user questions accurately.

{context}

Question: {question}
Answer in detail:"""

    # Construct the messages for Qwen chat template
    messages = [
        {"role": "system", "content": "You are Qwen, a helpful code assistant."},
        {"role": "user", "content": prompt}
    ]

    # Apply chat template
    text = tokenizer.apply_chat_template(
        messages,
        tokenize=False,
        add_generation_prompt=True
    )

    # Tokenize input
    model_inputs = tokenizer([text], return_tensors="pt").to(model.device)

    # Generate output
    generated_ids = model.generate(
        **model_inputs,
        max_new_tokens=512
    )

    # Remove input prompt from output
    generated_ids = [
        output_ids[len(input_ids):] 
        for input_ids, output_ids in zip(model_inputs.input_ids, generated_ids)
    ]

    # Decode generated text
    response = tokenizer.batch_decode(generated_ids, skip_special_tokens=True)[0]
    return response

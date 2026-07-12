#!/usr/bin/env python3
"""
Prism SFT Training Script for HuggingFace
Downloads data from GitHub, fine-tunes a small model, pushes to HF Hub.
Optimized for HF Spaces / single GPU training.
"""
import os
import json
import urllib.request
import sys

# ============================================================
# Config
# ============================================================
DATA_URL = "https://raw.githubusercontent.com/prism-invest-hqhub/prism-capital/main/datasets/cbond_sft_train.jsonl"
HF_TOKEN = os.environ.get("HF_TOKEN", "")
if not HF_TOKEN:
    print("ERROR: Set HF_TOKEN environment variable")
    sys.exit(1)
BASE_MODEL = "Qwen/Qwen2.5-1.5B"  # Small model, fits on any GPU
OUTPUT_REPO = "prism-invest-hqhub/prism-cbond-sft"  # Target HF repo
NUM_EPOCHS = 3
LR = 2e-5
BATCH_SIZE = 4
GRAD_ACCUM = 4  # effective batch = 16
MAX_SEQ_LEN = 512

# ============================================================
# Step 1: Download data
# ============================================================
print("=" * 60)
print("Step 1: Downloading training data...")
print("=" * 60)

urllib.request.urlretrieve(DATA_URL, "train_data.jsonl")
with open("train_data.jsonl") as f:
    data = [json.loads(line) for line in f]
print(f"Loaded {len(data)} training samples")

# ============================================================
# Step 2: Install dependencies (if needed)
# ============================================================
print("\nStep 2: Checking dependencies...")
try:
    import torch
    print(f"PyTorch: {torch.__version__}")
    print(f"CUDA available: {torch.cuda.is_available()}")
    if torch.cuda.is_available():
        print(f"GPU: {torch.cuda.get_device_name(0)}")
except ImportError:
    print("ERROR: PyTorch not installed. Run on a GPU-enabled environment.")
    sys.exit(1)

try:
    from transformers import AutoModelForCausalLM, AutoTokenizer, TrainingArguments
    from trl import SFTTrainer, SFTConfig
    print("transformers + trl: OK")
except ImportError:
    print("Installing dependencies...")
    os.system("pip install -q transformers trl datasets accelerate peft")
    from transformers import AutoModelForCausalLM, AutoTokenizer, TrainingArguments
    from trl import SFTTrainer, SFTConfig

try:
    from peft import LoraConfig, get_peft_model
    print("PEFT (LoRA): OK")
except ImportError:
    os.system("pip install -q peft")
    from peft import LoraConfig, get_peft_model

# ============================================================
# Step 3: Load tokenizer & model
# ============================================================
print(f"\nStep 3: Loading model {BASE_MODEL}...")
tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL, trust_remote_code=True)
if tokenizer.pad_token is None:
    tokenizer.pad_token = tokenizer.eos_token

model = AutoModelForCausalLM.from_pretrained(
    BASE_MODEL,
    torch_dtype=torch.float16 if torch.cuda.is_available() else torch.float32,
    device_map="auto" if torch.cuda.is_available() else None,
    trust_remote_code=True,
)

# LoRA config for efficient training
lora_config = LoraConfig(
    r=16,
    lora_alpha=32,
    target_modules=["q_proj", "v_proj", "k_proj", "o_proj"],
    lora_dropout=0.05,
    bias="none",
    task_type="CAUSAL_LM",
)
model = get_peft_model(model, lora_config)
model.print_trainable_parameters()

# ============================================================
# Step 4: Prepare dataset
# ============================================================
print("\nStep 4: Preparing dataset...")

def format_conversation(sample):
    """Format messages into ChatML-style text"""
    text = ""
    for msg in sample["messages"]:
        role = msg["role"]
        content = msg["content"]
        text += f"<|{role}|>\n{content}<|end|>\n"
    text += "<|assistant|>\n"  # No, this is wrong. Let me fix.
    return text

def format_for_training(sample):
    """Format as conversation text for SFT"""
    messages = sample["messages"]
    formatted = tokenizer.apply_chat_template(
        messages, tokenize=False, add_generation_prompt=False
    )
    return formatted

# Try chat template first, fallback to manual format
try:
    test = tokenizer.apply_chat_template(data[0]["messages"], tokenize=False)
    print("Using tokenizer chat template")
    format_fn = lambda s: tokenizer.apply_chat_template(s["messages"], tokenize=False, add_generation_prompt=False)
except Exception:
    print("Using manual ChatML format")
    def format_fn(sample):
        text = ""
        for msg in sample["messages"]:
            text += f"<|{msg['role']}|>\n{msg['content']}<|end|>\n"
        return text

from datasets import Dataset
train_dataset = Dataset.from_list(data)
train_dataset = train_dataset.map(lambda x: {"text": format_fn(x)})

# ============================================================
# Step 5: Train
# ============================================================
print("\nStep 5: Starting training...")
print(f"  Epochs: {NUM_EPOCHS}")
print(f"  LR: {LR}")
print(f"  Batch size: {BATCH_SIZE} x {GRAD_ACCUM} = {BATCH_SIZE * GRAD_ACCUM}")
print(f"  Samples: {len(train_dataset)}")

training_args = SFTConfig(
    output_dir="./prism-cbond-sft-output",
    num_train_epochs=NUM_EPOCHS,
    per_device_train_batch_size=BATCH_SIZE,
    gradient_accumulation_steps=GRAD_ACCUM,
    learning_rate=LR,
    logging_steps=5,
    save_strategy="epoch",
    warmup_ratio=0.1,
    fp16=torch.cuda.is_available(),
    max_seq_length=MAX_SEQ_LEN,
    report_to="none",
)

trainer = SFTTrainer(
    model=model,
    args=training_args,
    train_dataset=train_dataset,
    processing_class=tokenizer,
)

print("\n🚀 Training started...")
trainer.train()
print("\n✅ Training complete!")

# ============================================================
# Step 6: Save & Push to HF Hub
# ============================================================
print("\nStep 6: Pushing to HF Hub...")

# Merge LoRA weights
merged_model = model.merge_and_unload()
merged_model.save_pretrained("./prism-cbond-merged")
tokenizer.save_pretrained("./prism-cbond-merged")

# Push to hub
merged_model.push_to_hub(OUTPUT_REPO, token=HF_TOKEN, private=False)
tokenizer.push_to_hub(OUTPUT_REPO, token=HF_TOKEN)

print(f"\n🎉 Model pushed to: https://huggingface.co/{OUTPUT_REPO}")
print("Done!")

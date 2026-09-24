import os, re, time
import ollama
from dotenv import load_dotenv

load_dotenv()
_client = ollama.Client(host=os.getenv("OLLAMA_HOST", "http://localhost:11434"))
DEFAULT_MODEL = os.getenv("LLM_MODEL", "qwen2.5-coder:3b")
EMBED_MODEL = os.getenv("EMBED_MODEL", "nomic-embed-text")
NUM_CTX = int(os.getenv("NUM_CTX", "6144"))


def chat(messages, model=None, temperature=0.0):
    """Returns dict: text, latency_s, prompt_tokens, completion_tokens."""
    t0 = time.time()
    r = _client.chat(
        model=model or DEFAULT_MODEL,
        messages=messages,
        options={"temperature": temperature, "num_ctx": NUM_CTX, "seed": 42},
        keep_alive="30m",
    )
    return {
        "text": r["message"]["content"],
        "latency_s": time.time() - t0,
        "prompt_tokens": r.get("prompt_eval_count", 0),
        "completion_tokens": r.get("eval_count", 0),
    }


def extract_sql(text):
    """Small models often wrap SQL in ```sql fences or add chatter."""
    m = re.search(r"```(?:sql)?\s*(.*?)```", text, re.S | re.I)
    sql = (m.group(1) if m else text).strip()
    return sql.rstrip(";").strip() + ";"


def embed(texts):
    r = _client.embed(model=EMBED_MODEL, input=texts)
    return r["embeddings"]
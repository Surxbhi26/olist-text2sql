"""LLM client with a provider switch. Set LLM_PROVIDER=ollama or claude in .env."""
import json
import os
import time
import urllib.error
import urllib.request

from dotenv import load_dotenv

load_dotenv()

PROVIDER = os.getenv("LLM_PROVIDER", "ollama").lower()
# Accepts either naming style in .env (OLLAMA_HOST / LLM_MODEL / NUM_CTX or the OLLAMA_* names).
OLLAMA_URL = os.getenv("OLLAMA_HOST") or os.getenv("OLLAMA_URL") or "http://localhost:11434"
OLLAMA_MODEL = os.getenv("LLM_MODEL") or os.getenv("OLLAMA_MODEL") or "qwen2.5-coder:7b"
NUM_CTX = int(os.getenv("NUM_CTX", "8192"))
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-5")


def model_name():
    return OLLAMA_MODEL if PROVIDER == "ollama" else CLAUDE_MODEL


def chat(system, user, temperature=0.0):
    """Send one system + user message (temperature 0 by default, for reproducibility).
    Returns {text, input_tokens, output_tokens, latency_s, model}."""
    start = time.time()
    if PROVIDER == "ollama":
        text, tin, tout = _ollama(system, user, temperature)
    elif PROVIDER == "claude":
        text, tin, tout = _claude(system, user, temperature)
    else:
        raise ValueError(f"Unknown LLM_PROVIDER: {PROVIDER}")
    return {"text": text, "input_tokens": tin, "output_tokens": tout,
            "latency_s": round(time.time() - start, 2), "model": model_name()}


def _ollama(system, user, temperature):
    body = json.dumps({
        "model": OLLAMA_MODEL,
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": user}],
        "stream": False,
        # num_ctx matters: Ollama's default context is small and would silently cut off
        # the schema context, which causes hallucinated columns.
        "options": {"temperature": temperature, "num_ctx": NUM_CTX},
        # Keep the model in memory between runs, so each question doesn't pay the load time.
        "keep_alive": os.getenv("OLLAMA_KEEP_ALIVE", "30m"),
    }).encode()
    req = urllib.request.Request(f"{OLLAMA_URL}/api/chat", data=body,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=600) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Ollama error {e.code}: {e.read().decode()[:300]}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"Ollama not reachable at {OLLAMA_URL}. Is it running?") from e
    return (data["message"]["content"],
            data.get("prompt_eval_count", 0), data.get("eval_count", 0))


def _claude(system, user, temperature):
    import anthropic
    client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from the environment
    resp = client.messages.create(model=CLAUDE_MODEL, max_tokens=1024, temperature=temperature,
                                  system=system, messages=[{"role": "user", "content": user}])
    text = "".join(b.text for b in resp.content if b.type == "text")
    return text, resp.usage.input_tokens, resp.usage.output_tokens


if __name__ == "__main__":
    r = chat("You are a helpful assistant.", "Reply with exactly: pong")
    print(r)
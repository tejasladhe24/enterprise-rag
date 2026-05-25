import hashlib
import tiktoken

encoding = tiktoken.get_encoding("cl100k_base")


def sha256_digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def estimate_tokens(text: str) -> int:
    return len(encoding.encode(text))

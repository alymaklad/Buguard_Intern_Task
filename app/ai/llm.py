"""
LLM initialization using LangChain + Groq.
Reads configuration from environment variables — keys never hardcoded.
"""
import os
from dotenv import load_dotenv
from langchain_groq import ChatGroq

load_dotenv()

_llm_instance = None


def get_llm() -> ChatGroq:
    """
    Returns a singleton ChatGroq instance.
    Model defaults to llama-3.3-70b-versatile (strong structured output support).
    """
    global _llm_instance
    if _llm_instance is None:
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            raise RuntimeError("GROQ_API_KEY environment variable is not set.")
        model = os.getenv("LLM_MODEL", "llama-3.3-70b-versatile")
        _llm_instance = ChatGroq(
            groq_api_key=api_key,
            model_name=model,
            temperature=0,          # deterministic output for structured tasks
        )
    return _llm_instance

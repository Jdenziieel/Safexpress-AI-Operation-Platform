"""Configuration for PDF parsing Lambda."""
import os


class Config:
    """Application configuration class for Lambda."""
    
    # OpenAI Configuration
    # OPENAI_MODEL = primary chunking + image-analysis model. gpt-4.1 chosen
    # here per supervisor-agent model-change guide §2: PDF chunking uses a
    # heavy repeatable system prompt every call → 75% cache discount compounds
    # across a multi-page document. 1M context also lets us pass larger pages
    # without splitting. Env-overridable for easy per-environment tuning.
    # OPENAI_MINI_MODEL = short helper calls (classification, light cleanup).
    # Kept on gpt-4o-mini since those prompts don't repeat and cold cost is
    # ~4x cheaper than gpt-4.1-mini.
    OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
    OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4.1")
    OPENAI_MINI_MODEL = os.environ.get("OPENAI_MINI_MODEL", "gpt-4o-mini")
    EMBEDDING_MODEL = "text-embedding-3-small"
    EMBEDDING_DIMENSIONS = 1536
    
    # Processing Configuration
    BATCH_SIZE = 100
    MAX_TOKENS = 1000
    TEMPERATURE = 0.0
    TOP_M_RERANK = 10

    # AI chunking input/output limits.
    # CHUNKING_INPUT_CHAR_CAP — maximum characters of cleaned PDF text we will
    # send to the chunking model in one call. The previous hard-coded cap was
    # 20,000 chars, which silently dropped everything beyond ~5 pages of a
    # typical SOP. We raised the default to 100,000 (~25K tokens with gpt-4.1)
    # and made it env-configurable so customers with very long documents can
    # tune it without a redeploy. When the cap is hit we now log a WARNING
    # and the lambda emits fallback chunks for the dropped lines.
    # CHUNKING_OUTPUT_MAX_TOKENS — explicit response cap so the JSON object
    # cannot be truncated mid-string, which previously broke json.loads and
    # silently produced zero chunks.
    CHUNKING_INPUT_CHAR_CAP = int(os.environ.get("CHUNKING_INPUT_CHAR_CAP", "100000"))
    CHUNKING_OUTPUT_MAX_TOKENS = int(os.environ.get("CHUNKING_OUTPUT_MAX_TOKENS", "16384"))

    # PDF Processing Configuration
    LINE_TOLERANCE = 5
    WORD_TOLERANCE_MULTIPLIER = 0.4
    GAP_MULTIPLIER = 1.5
    # MATCH_SCORE_THRESHOLD — minimum fuzzy-match score (0-100, RapidFuzz)
    # for an AI chunk to be visually anchored to a PDF line. The previous
    # value of 80 rejected most rephrased / lightly summarised chunks
    # (which still legitimately came from those lines), so the chunk would
    # appear in the chunk list but never highlight on click. 60 gives the
    # AI room to paraphrase while still rejecting clear mismatches.
    # Env-overridable for tuning per document type.
    MATCH_SCORE_THRESHOLD = int(os.environ.get("MATCH_SCORE_THRESHOLD", "60"))
    CROSS_PAGE_LINE_WINDOW = 20
    
    @classmethod
    def validate(cls):
        """Validate required configuration."""
        if not cls.OPENAI_API_KEY:
            raise RuntimeError("❌ OPENAI_API_KEY environment variable is not set!")
        return True

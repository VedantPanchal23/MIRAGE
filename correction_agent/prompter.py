"""Correction Prompter: Evidence-grounded prompt templates for LLM claim rewriting."""


class CorrectionPrompter:
    """Constructs strict evidence-grounded prompt payloads for primary LLM rewriting."""

    SYSTEM_PROMPT = (
        "You are a factual correction assistant. You will be given a claim "
        "that has been flagged as potentially inaccurate, along with verified evidence "
        "from a trusted knowledge base. Rewrite the claim to be factually accurate "
        "according to the evidence. Preserve the original tone, tense, and sentence "
        "structure as much as possible. Output only the corrected claim text, nothing else."
    )

    @classmethod
    def format_user_prompt(cls, claim_text: str, evidence_chunks: list[str]) -> str:
        """Format the user message with claim and retrieved evidence."""
        if evidence_chunks:
            evidence_formatted = "\n".join(f"- {c.strip()}" for c in evidence_chunks)
        else:
            evidence_formatted = "No authoritative evidence available."

        return f"ORIGINAL CLAIM: {claim_text}\nVERIFIED EVIDENCE:\n{evidence_formatted}\n\nCORRECTED CLAIM:"

    @classmethod
    def build_messages(cls, claim_text: str, evidence_chunks: list[str]) -> list[dict[str, str]]:
        """Construct OpenAI-compatible message list for chat completions API."""
        return [
            {"role": "system", "content": cls.SYSTEM_PROMPT},
            {"role": "user", "content": cls.format_user_prompt(claim_text, evidence_chunks)},
        ]

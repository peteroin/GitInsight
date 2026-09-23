import os
import re

from groq import Groq

MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-20b")
MAX_CONTEXT_CHARS = 14_000


def build_context(chunks):
    sections = []
    total = 0

    for chunk in chunks:
        header = (
            f"FILE: {chunk['path']}\n"
            f"TYPE: {chunk.get('kind', 'code')}\n"
            f"CHUNK: {chunk.get('chunk_index', 0)}\n\n"
        )

        remaining = MAX_CONTEXT_CHARS - total - len(header)

        if remaining <= 0:
            break

        body = chunk["content"][:remaining]
        sections.append(header + body)
        total += len(header) + len(body)

    return "\n\n==============================\n\n".join(sections)


def clean_model_markdown(text: str) -> str:
    """Convert common Markdown into clean plain text for the chat UI."""
    text = text.replace("\\*", "*").replace("\\#", "#")

    # Markdown headings.
    text = re.sub(r"^\s{0,3}#{1,6}\s*", "", text, flags=re.MULTILINE)

    # Bold / italic / inline code.
    text = re.sub(r"\*\*(.*?)\*\*", r"\1", text, flags=re.DOTALL)
    text = re.sub(r"__(.*?)__", r"\1", text, flags=re.DOTALL)
    text = re.sub(r"(?<!\w)\*(.*?)\*(?!\w)", r"\1", text, flags=re.DOTALL)
    text = re.sub(r"(?<!\w)_(.*?)_(?!\w)", r"\1", text, flags=re.DOTALL)
    text = re.sub(r"`([^`]+)`", r"\1", text)

    # Markdown links: [text](url) -> text
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)

    # Markdown table separator rows.
    text = re.sub(
        r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)+\|?\s*$",
        "",
        text,
        flags=re.MULTILINE,
    )

    # Convert table rows to readable text.
    def table_row(match):
        cells = [
            cell.strip()
            for cell in match.group(1).split("|")
            if cell.strip()
        ]
        return "  •  ".join(cells)

    text = re.sub(
        r"^\s*\|(.+)\|\s*$",
        table_row,
        text,
        flags=re.MULTILINE,
    )

    # Bullets.
    text = re.sub(r"^\s*[-*+]\s+", "• ", text, flags=re.MULTILINE)

    # Remove unnecessary horizontal rules.
    text = re.sub(r"^\s*[-_=]{3,}\s*$", "", text, flags=re.MULTILINE)

    # Clean repeated blank lines.
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()


def answer(question, chunks):
    api_key = os.getenv("GROQ_API_KEY")

    if not api_key:
        raise RuntimeError(
            "GROQ_API_KEY is not configured. Add it to backend/.env."
        )

    context = build_context(chunks)

    prompt = f"""
You are GitInsight, an AI assistant that explains software repositories.

Answer the user's question using only the supplied repository context.

Rules:
1. Do not invent files, functions, APIs, dependencies, or implementation details.
2. Mention exact filenames when useful.
3. For broad questions, explain the repository purpose, major parts,
   important files, dependencies, and how the parts connect.
4. If something cannot be determined from the context, say so.
5. Use simple, professional English.
6. Do NOT use Markdown formatting.
7. Do NOT use # headings, **bold**, *italics*, Markdown tables,
   backticks, or Markdown links.
8. Use plain section titles and normal bullet characters only.
9. Do not add decorative symbols.

USER QUESTION:
{question}

REPOSITORY CONTEXT:
{context}
"""

    client = Groq(api_key=api_key)

    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a precise software repository analysis assistant. "
                    "Return clean plain text, not Markdown."
                ),
            },
            {
                "role": "user",
                "content": prompt,
            },
        ],
        temperature=0.1,
        max_completion_tokens=1200,
    )

    return clean_model_markdown(response.choices[0].message.content or "")

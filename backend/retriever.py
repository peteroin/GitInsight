import re
from pathlib import Path

TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_$.-]*")

STOPWORDS = {
    "the", "and", "for", "with", "from", "this", "that", "what",
    "how", "does", "are", "is", "to", "in", "of", "a", "an", "on",
    "by", "it", "be", "can", "where", "which", "show", "explain",
    "tell", "me", "about", "please", "could", "would", "does",
}

IMPORTANT_FILES = {
    "readme.md",
    "package.json",
    "requirements.txt",
    "pyproject.toml",
    "dockerfile",
    "docker-compose.yml",
    "docker-compose.yaml",
    "render.yaml",
    "vercel.json",
    "vite.config.js",
    "vite.config.ts",
    "tsconfig.json",
}

SOURCE_EXTENSIONS = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"
}

CONFIG_EXTENSIONS = {
    ".json", ".yaml", ".yml", ".toml"
}

MAX_CHUNKS = 3000
CHUNK_SIZE = 1400
CHUNK_OVERLAP = 180
MAX_FILE_SIZE = 250_000


def tokens(text: str):
    result = []

    for token in TOKEN_RE.findall(text.lower()):
        token = token.strip("._-$")

        if len(token) < 2:
            continue

        if token in STOPWORDS:
            continue

        result.append(token)

    return result


def token_set(text: str):
    return set(tokens(text))


def make_chunk(path: str, content: str, index: int, kind="code"):
    return {
        "path": path,
        "chunk_index": index,
        "content": content,
        "tokens": list(token_set(content)),
        "kind": kind,
    }


def chunk_text(path: str, text: str, kind="code"):
    chunks = []

    start = 0
    index = 0

    while start < len(text) and len(chunks) < MAX_CHUNKS:
        end = min(start + CHUNK_SIZE, len(text))

        chunks.append(
            make_chunk(
                path=path,
                content=text[start:end],
                index=index,
                kind=kind,
            )
        )

        index += 1

        if end >= len(text):
            break

        start = max(end - CHUNK_OVERLAP, start + 1)

    return chunks


def read_text_file(path: Path):
    try:
        if path.stat().st_size > MAX_FILE_SIZE:
            return None

        return path.read_text(
            encoding="utf-8",
            errors="ignore",
        )
    except OSError:
        return None


def build_project_overview(root: Path, analysis):
    stats = analysis.get("stats", {})
    files = analysis.get("files", [])
    edges = analysis.get("edges", [])

    lines = [
        "GITINSIGHT PROJECT OVERVIEW",
        "",
        f"Total analyzed source files: {stats.get('files', 0)}",
        f"Internal dependencies: {stats.get('dependencies', 0)}",
        f"Python files: {stats.get('python_files', 0)}",
        f"JavaScript/TypeScript files: {stats.get('javascript_files', 0)}",
        "",
        "SOURCE FILES:",
    ]

    for item in files[:500]:
        lines.append(f"- {item['path']}")

    lines.extend([
        "",
        "INTERNAL DEPENDENCY RELATIONSHIPS:",
    ])

    for edge in edges[:1000]:
        lines.append(f"- {edge['source']} -> {edge['target']}")

    return "\n".join(lines)


def build_file_map(analysis):
    lines = [
        "REPOSITORY FILE MAP",
        "",
        "Each entry contains the file path and imports detected by the analyzer.",
        "",
    ]

    for item in analysis.get("files", []):
        imports = item.get("imports", [])

        if imports:
            lines.append(
                f"{item['path']} imports: {', '.join(imports[:20])}"
            )
        else:
            lines.append(f"{item['path']} imports: none detected")

    return "\n".join(lines)


def build_index(repo, analysis):
    root = Path(repo)
    chunks = []

    # These synthetic chunks make broad questions such as
    # "explain the project" work without requiring embeddings.
    overview = build_project_overview(root, analysis)
    chunks.append(
        make_chunk(
            "__PROJECT_OVERVIEW__",
            overview,
            0,
            kind="overview",
        )
    )

    file_map = build_file_map(analysis)
    chunks.append(
        make_chunk(
            "__FILE_MAP__",
            file_map,
            0,
            kind="file_map",
        )
    )

    # Index source code.
    for item in analysis.get("files", []):
        if len(chunks) >= MAX_CHUNKS:
            break

        path = item["path"]
        file_path = root / path
        text = read_text_file(file_path)

        if not text:
            continue

        remaining = MAX_CHUNKS - len(chunks)
        chunks.extend(chunk_text(path, text, kind="code")[:remaining])

    # Also index important documentation/configuration files.
    # This improves project-level questions significantly.
    for path in root.rglob("*"):
        if len(chunks) >= MAX_CHUNKS:
            break

        if not path.is_file():
            continue

        relative = path.relative_to(root).as_posix()
        lower_name = path.name.lower()

        if any(
            part in {
                ".git", "node_modules", "dist", "build",
                ".next", "__pycache__", ".venv", "venv"
            }
            for part in path.relative_to(root).parts
        ):
            continue

        is_important = (
            lower_name in IMPORTANT_FILES
            or path.suffix.lower() in CONFIG_EXTENSIONS
            and path.stat().st_size <= MAX_FILE_SIZE
        )

        if not is_important:
            continue

        # Avoid adding source files a second time.
        if path.suffix.lower() in SOURCE_EXTENSIONS:
            continue

        text = read_text_file(path)

        if not text:
            continue

        remaining = MAX_CHUNKS - len(chunks)
        chunks.extend(
            chunk_text(
                relative,
                text,
                kind="documentation",
            )[:remaining]
        )

    return chunks


def query_terms(question: str):
    terms = token_set(question)

    # Small synonym expansion improves natural-language questions
    # without needing an embedding model.
    synonyms = {
        "project": {"repository", "architecture", "application", "app"},
        "architecture": {"structure", "design", "project", "repository"},
        "database": {"db", "mongodb", "postgresql", "mysql", "sqlite"},
        "authentication": {"auth", "login", "jwt", "token", "session"},
        "authorization": {"auth", "role", "permission", "middleware"},
        "frontend": {"react", "vue", "angular", "ui", "client"},
        "backend": {"server", "api", "express", "fastapi", "route"},
        "api": {"route", "endpoint", "controller"},
        "dependency": {"import", "require", "module"},
        "payment": {"stripe", "checkout", "billing", "subscription"},
        "email": {"mail", "smtp", "sendgrid", "resend", "notification"},
    }

    expanded = set(terms)

    for term in terms:
        expanded.update(synonyms.get(term, set()))

    return expanded


def search(chunks, question, top_k=8):
    q = query_terms(question)

    if not chunks:
        return []

    broad = len(q) <= 3 or any(
        phrase in question.lower()
        for phrase in (
            "explain the project",
            "explain project",
            "project overview",
            "how does this project work",
            "how does the project work",
            "architecture",
            "overall structure",
            "repository structure",
        )
    )

    scored = []

    for chunk in chunks:
        content_terms = set(chunk.get("tokens", []))
        path_terms = token_set(chunk["path"])

        overlap = len(q & content_terms)
        path_overlap = len(q & path_terms)

        score = overlap * 2.0 + path_overlap * 4.0

        # Documentation and project overview are especially useful
        # for broad questions.
        if broad:
            if chunk["kind"] == "overview":
                score += 18
            elif chunk["kind"] == "file_map":
                score += 12
            elif chunk["kind"] == "documentation":
                score += 8

        # Path/name matches are valuable for questions such as
        # "where is authentication handled?"
        if any(term in chunk["path"].lower() for term in q):
            score += 5

        # Exact phrase matches provide another lightweight signal.
        question_lower = question.lower()
        content_lower = chunk["content"].lower()

        for term in q:
            if len(term) >= 5 and term in content_lower:
                score += 0.75

        if score > 0:
            scored.append((score, chunk))

    # For a broad question, always provide the project overview.
    if broad:
        overview = next(
            (c for c in chunks if c["kind"] == "overview"),
            None,
        )
        if overview and not any(c is overview for _, c in scored):
            scored.append((18, overview))

        file_map = next(
            (c for c in chunks if c["kind"] == "file_map"),
            None,
        )
        if file_map and not any(c is file_map for _, c in scored):
            scored.append((12, file_map))

    scored.sort(
        key=lambda item: (
            item[0],
            item[1]["kind"] == "overview",
        ),
        reverse=True,
    )

    return [chunk for _, chunk in scored[:top_k]]

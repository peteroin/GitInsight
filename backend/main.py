import re
import shutil
import subprocess
import tempfile
import uuid
from collections import OrderedDict
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from analyzer import analyze_repository
from retriever import build_index, search
from rag import answer

load_dotenv()

app = FastAPI(title="GitInsight API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Keep only a small number of repositories in memory.
# This is important on low-memory Render instances.
MAX_ACTIVE_REPOS = 2
REPOS = OrderedDict()

DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"


class AnalyzeRequest(BaseModel):
    repo_url: str = Field(min_length=1, max_length=500)


class ChatRequest(BaseModel):
    repo_id: str
    question: str = Field(min_length=1, max_length=2000)


def valid_github_url(url: str) -> bool:
    pattern = r"^https?://github\.com/[^/\s]+/[^/\s#?]+/?(?:\.git)?$"
    return bool(re.match(pattern, url.strip(), re.I))


def clone_repository(url: str):
    url = url.strip()

    if not valid_github_url(url):
        raise HTTPException(
            status_code=400,
            detail="Please provide a valid public GitHub repository URL.",
        )

    repo_id = uuid.uuid4().hex[:12]
    work_dir = Path(tempfile.mkdtemp(prefix="gitinsight_"))
    repo_dir = work_dir / "repo"

    command = [
        "git",
        "clone",
        "--depth",
        "1",
        "--filter=blob:none",
        url,
        str(repo_dir),
    ]

    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=120,
    )

    if result.returncode != 0:
        shutil.rmtree(work_dir, ignore_errors=True)
        message = result.stderr.strip()[-1500:] or "GitHub repository clone failed."
        raise HTTPException(status_code=400, detail=message)

    return repo_id, work_dir, repo_dir


def remove_old_repositories():
    while len(REPOS) >= MAX_ACTIVE_REPOS:
        _, old = REPOS.popitem(last=False)
        shutil.rmtree(old["work"], ignore_errors=True)


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "active_repositories": len(REPOS),
    }


@app.post("/api/analyze")
def analyze(req: AnalyzeRequest):
    repo_id, work_dir, repo_dir = clone_repository(req.repo_url)

    try:
        data = analyze_repository(str(repo_dir))
        chunks = build_index(str(repo_dir), data)

        remove_old_repositories()

        REPOS[repo_id] = {
            "repo_url": req.repo_url.strip(),
            "work": str(work_dir),
            "repo": str(repo_dir),
            "data": data,
            "chunks": chunks,
        }

        # React Flow receives valid initial positions.
        # Graph.jsx will calculate the final layout.
        nodes = [
            {
                "id": path,
                "type": "default",
                "data": {"label": path},
                "position": {"x": 0, "y": 0},
            }
            for path in data["nodes"]
        ]

        edges = [
            {
                "id": f"{edge['source']}->{edge['target']}",
                "source": edge["source"],
                "target": edge["target"],
                "type": "smoothstep",
                "animated": False,
            }
            for edge in data["edges"]
        ]

        return {
            "repo_id": repo_id,
            "repo_url": req.repo_url.strip(),
            "stats": data["stats"],
            "files": data["files"],
            "nodes": nodes,
            "edges": edges,
        }

    except HTTPException:
        shutil.rmtree(work_dir, ignore_errors=True)
        raise
    except Exception as exc:
        shutil.rmtree(work_dir, ignore_errors=True)
        raise HTTPException(
            status_code=500,
            detail=f"Repository analysis failed: {exc}",
        )


@app.post("/api/chat")
def chat(req: ChatRequest):
    repo = REPOS.get(req.repo_id)

    if not repo:
        raise HTTPException(
            status_code=404,
            detail="Repository session not found. Analyze the repository again.",
        )

    # Move recently used repository to the end of the LRU store.
    REPOS.move_to_end(req.repo_id)

    hits = search(repo["chunks"], req.question, top_k=8)

    if not hits:
        return {
            "answer": (
                "I could not find enough indexed repository information "
                "to answer that question."
            ),
            "sources": [],
        }

    try:
        response = answer(req.question, hits)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    sources = list(dict.fromkeys(chunk["path"] for chunk in hits))

    return {
        "answer": response,
        "sources": sources,
    }


@app.get("/api/repository/{repo_id}/file")
def get_file(repo_id: str, path: str):
    repo = REPOS.get(repo_id)

    if not repo:
        raise HTTPException(status_code=404, detail="Repository session not found.")

    root = Path(repo["repo"]).resolve()
    target = (root / path).resolve()

    # Prevent ../ path traversal.
    if root != target and root not in target.parents:
        raise HTTPException(status_code=403, detail="Invalid file path.")

    if not target.is_file():
        raise HTTPException(status_code=404, detail="File not found.")

    if target.stat().st_size > 500_000:
        raise HTTPException(status_code=413, detail="File is too large to display.")

    return {
        "path": path,
        "content": target.read_text(encoding="utf-8", errors="ignore"),
    }


if DIST.exists():
    app.mount(
        "/",
        StaticFiles(directory=DIST, html=True),
        name="frontend",
    )

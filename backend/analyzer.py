import ast,re
from pathlib import Path

EXT={".py",".js",".jsx",".ts",".tsx",".mjs",".cjs"}
IGNORE={".git","node_modules","__pycache__",".venv","venv","dist","build",".next",".pytest_cache",".mypy_cache"}
MAX_FILES=500
MAX_SIZE=300000

def collect(root):
    out=[]
    for p in root.rglob("*"):
        if not p.is_file() or p.suffix.lower() not in EXT: continue
        if any(x in IGNORE for x in p.relative_to(root).parts): continue
        try:
            if p.stat().st_size>MAX_SIZE: continue
        except OSError: continue
        out.append(p)
        if len(out)>=MAX_FILES: break
    return out

def py_imports(text):
    out=[]
    try: tree=ast.parse(text)
    except SyntaxError: return out
    for n in ast.walk(tree):
        if isinstance(n,ast.Import): out += [a.name for a in n.names]
        elif isinstance(n,ast.ImportFrom) and n.module: out.append(n.module)
    return out

JS_RE=re.compile(r"""(?:import\s+(?:[\s\S]*?\s+from\s+)?|export\s+[\s\S]*?\s+from\s+|require\s*\(\s*)['"]([^'"]+)['"]""")

def js_imports(text): return JS_RE.findall(text)

def resolve(source,name,root):
    if not name.startswith("."): return None
    base=(source.parent/name).resolve()
    candidates=[base]+[Path(str(base)+e) for e in [".js",".jsx",".ts",".tsx",".mjs",".cjs"]]
    candidates += [base/f"index{e}" for e in [".js",".jsx",".ts",".tsx",".mjs",".cjs"]]
    for p in candidates:
        if p.is_file() and root in p.parents: return p
    return None

def analyze_repository(repo_dir):
    root=Path(repo_dir).resolve(); paths=collect(root); known={p.resolve() for p in paths}
    files=[]; edges=[]
    for p in paths:
        rel=p.relative_to(root).as_posix()
        text=p.read_text(encoding="utf-8",errors="ignore")
        imports=py_imports(text) if p.suffix.lower()==".py" else js_imports(text)
        files.append({"path":rel,"extension":p.suffix.lower(),"size":len(text),"imports":imports})
    for f in files:
        source=(root/f["path"]).resolve()
        for name in f["imports"]:
            target=resolve(source,name,root)
            if target and target in known:
                edges.append({"source":f["path"],"target":target.relative_to(root).as_posix()})
    return {"files":files,"nodes":[f["path"] for f in files],"edges":edges,
            "stats":{"files":len(files),"dependencies":len(edges),
                     "python_files":sum(f["extension"]==".py" for f in files),
                     "javascript_files":sum(f["extension"] in EXT- {".py"} for f in files)}}

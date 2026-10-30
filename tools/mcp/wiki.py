"""llm-wiki 核心库。

贴合现有目录结构（entities/concepts/sources/analysis 在顶层）+ Obsidian `[[wikilink]]`。
提供页面读写、短名解析、索引/日志维护、全文搜索与 lint 健康检查。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Optional

# 四个内容目录（相对 wiki 根）
CONTENT_DIRS = ("entities", "concepts", "sources", "analysis")

# frontmatter 分隔
_FM_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?", re.DOTALL)

# wikilink：[[name]] 或 [[name|display]]
_WIKILINK_RE = re.compile(r"\[\[([^\[\]|]+)(?:\|([^\[\]]+))?\]\]")

# 索引条目行：- [[name]] — 描述
_INDEX_ENTRY_RE = re.compile(r"^-\s*\[\[([^\[\]|]+)(?:\|[^\[\]]+)?\]\]")

# 日志条目行：## [YYYY-MM-DD] verb | title
_LOG_ENTRY_RE = re.compile(r"^##\s*\[(\d{4}-\d{2}-\d{2})\]\s*(\w+)\s*\|\s*(.+)$")


def slugify(name: str) -> str:
    """把任意标题转成小写连字符文件名（不含扩展名）。"""
    s = name.strip().lower()
    s = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "-", s)
    s = s.strip("-")
    return s


@dataclass
class WikiRoot:
    """wiki 根目录，封装路径解析。"""
    root: Path

    def dir(self, kind: str) -> Path:
        if kind not in CONTENT_DIRS:
            raise ValueError(f"未知内容目录: {kind}")
        return self.root / kind

    @property
    def index_path(self) -> Path:
        return self.root / "index.md"

    @property
    def log_path(self) -> Path:
        return self.root / "log.md"

    def iter_pages(self) -> list[Path]:
        """列出所有内容页 .md 文件。"""
        out: list[Path] = []
        for kind in CONTENT_DIRS:
            d = self.dir(kind)
            if d.is_dir():
                out.extend(sorted(d.glob("*.md")))
        return out

    def iter_sources(self) -> list[Path]:
        """源文件页（sources 目录下）。"""
        d = self.dir("sources")
        return sorted(d.glob("*.md")) if d.is_dir() else []

    def resolve(self, name: str) -> Optional[Path]:
        """按短名解析到唯一文件。

        name 可以是文件名（不带扩展名）、带相对目录，或 wikilink 短名。
        在四个目录中查找唯一匹配；若同名在多个目录出现则优先 entities。
        """
        name = name.strip()
        # 去掉可能的 .md 扩展
        if name.endswith(".md"):
            name = name[:-3]
        # 显式目录路径
        if "/" in name or "\\" in name:
            p = self.root / (name + ".md")
            return p if p.is_file() else None
        # 短名：按优先级找
        for kind in CONTENT_DIRS:
            p = self.dir(kind) / (name + ".md")
            if p.is_file():
                return p
        # 宽松匹配：忽略大小写 / 连字符差异
        target = slugify(name)
        if not target:
            return None
        for p in self.iter_pages():
            if slugify(p.stem) == target:
                return p
        return None


@dataclass
class Page:
    """一个 wiki 页：frontmatter + 正文。"""
    path: Path
    kind: str  # entities / concepts / sources / analysis
    frontmatter: dict = field(default_factory=dict)
    body: str = ""

    @property
    def name(self) -> str:
        return self.path.stem

    @property
    def title(self) -> str:
        return self.frontmatter.get("title", self.name)

    @property
    def wikilinks(self) -> list[str]:
        """正文里引用的所有 wikilink 短名（去重，保持顺序）。"""
        seen: list[str] = []
        for m in _WIKILINK_RE.finditer(self.body):
            n = m.group(1).strip()
            if n not in seen:
                seen.append(n)
        return seen


# 解析 tags/sources/related 这类 list 字段：兼容 [[a]], [[b]] 与 [a, b] 与 ["a", "b"] 三种形式。
# 与 build.py 的 parse_frontmatter 保持一致，提取纯短名（去掉 [[ ]]）。
_LIST_ITEM_RE = re.compile(r"\[\[([^\]]+)\]\]|\"([^\"]+)\"|'([^']+)'|([^,\[\]\s]+)")

# 用 [[ ]] 形式（wikilink）写回的字段，其余 list 用 [a, b] 形式。
_WIKILINK_LIST_FIELDS = {"related"}


def _parse_list(v: str) -> list[str]:
    """从 list 字段值提取纯短名列表。"""
    items = _LIST_ITEM_RE.findall(v)
    flat = [a or b or c or d for (a, b, c, d) in items]
    flat = [x.strip().strip('"').strip("'").strip("[").strip("]") for x in flat]
    return [x for x in flat if x]


def parse_frontmatter(text: str) -> tuple[dict, str]:
    """把完整文件文本拆成 (frontmatter dict, body)。"""
    m = _FM_RE.match(text)
    if not m:
        return {}, text.strip()
    body = text[m.end():].strip()
    fm: dict = {}
    for line in m.group(1).splitlines():
        line = line.strip()
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        k = k.strip()
        v = v.strip()
        if k in ("tags", "sources", "related"):
            fm[k] = _parse_list(v)
        elif (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
            fm[k] = v[1:-1]
        else:
            fm[k] = v
    return fm, body


def render_frontmatter(fm: dict, body: str) -> str:
    lines = ["---"]
    for k, v in fm.items():
        if v is None or v == "":
            continue
        if isinstance(v, list):
            if k in _WIKILINK_LIST_FIELDS:
                # related 用 [[a]], [[b]] 形式（与现有内容一致）
                inner = ", ".join(f"[[{x}]]" for x in v)
                lines.append(f"{k}: {inner}")
            else:
                # tags / sources 用 [a, b] 形式
                inner = ", ".join(str(x) for x in v)
                lines.append(f"{k}: [{inner}]")
        else:
            lines.append(f"{k}: {v}")
    lines.append("---")
    return "\n".join(lines) + "\n\n" + body.rstrip() + "\n"


def read_page(root: WikiRoot, path: Path) -> Page:
    kind = path.parent.name if path.parent.name in CONTENT_DIRS else "unknown"
    text = path.read_text(encoding="utf-8")
    fm, body = parse_frontmatter(text)
    return Page(path=path, kind=kind, frontmatter=fm, body=body)


def write_page(path: Path, fm: dict, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_frontmatter(fm, body), encoding="utf-8")


# ---------- 索引 ----------

def read_index_entries(root: WikiRoot) -> list[dict]:
    """从 index.md 解析条目：{name, desc}。"""
    if not root.index_path.is_file():
        return []
    out: list[dict] = []
    for line in root.index_path.read_text(encoding="utf-8").splitlines():
        m = _INDEX_ENTRY_RE.match(line)
        if m:
            name = m.group(1).strip()
            desc = line.split("—", 1)[1].strip() if "—" in line else ""
            out.append({"name": name, "desc": desc})
    return out


def upsert_index_entry(root: WikiRoot, name: str, desc: str) -> None:
    """在 index.md 中新增或更新一个条目。缺失时追加到末尾。"""
    text = root.index_path.read_text(encoding="utf-8")
    lines = text.splitlines()
    new_line = f"- [[{name}]] — {desc}".rstrip()
    replaced = False
    for i, line in enumerate(lines):
        m = _INDEX_ENTRY_RE.match(line)
        if m and m.group(1).strip() == name:
            lines[i] = new_line
            replaced = True
            break
    if not replaced:
        if lines and lines[-1].strip() == "":
            lines.append(new_line)
        else:
            lines.append("")
            lines.append(new_line)
    root.index_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def remove_index_entry(root: WikiRoot, name: str) -> None:
    if not root.index_path.is_file():
        return
    lines = root.index_path.read_text(encoding="utf-8").splitlines()
    lines = [l for l in lines if not (_INDEX_ENTRY_RE.match(l) and _INDEX_ENTRY_RE.match(l).group(1).strip() == name)]
    root.index_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ---------- 日志 ----------

def append_log(root: WikiRoot, verb: str, title: str, details: str = "") -> None:
    """追加日志条目到 log.md 顶部（最新在上）。"""
    today = date.today().isoformat()
    entry = f"## [{today}] {verb} | {title}"
    if details:
        entry += "\n\n" + details.strip()
    if root.log_path.is_file():
        text = root.log_path.read_text(encoding="utf-8")
        # 找到 frontmatter 结束位置，在正文最前插入
        m = _FM_RE.match(text)
        if m:
            head = text[: m.end()]
            rest = text[m.end():].lstrip("\n")
            new = head + "\n" + entry + "\n\n" + rest
        else:
            new = entry + "\n\n" + text
        root.log_path.write_text(new, encoding="utf-8")
    else:
        fm = {"title": "操作日志", "date": today}
        root.log_path.write_text(render_frontmatter(fm, entry), encoding="utf-8")


# ---------- 搜索 ----------

def query(root: WikiRoot, query: str, limit: int = 20) -> list[dict]:
    """加权全文搜索：标题权重 > frontmatter > 正文。返回 [{path, kind, title, score, snippet}]。"""
    q = query.lower()
    results: list[dict] = []
    for p in root.iter_pages():
        page = read_page(root, p)
        score = 0
        title = page.title.lower()
        body_l = page.body.lower()
        if q in title:
            score += 10
        if q in body_l:
            score += 3
        # 计算出现次数，小幅加权
        score += body_l.count(q)
        if score <= 0:
            continue
        # 摘要：正文前 120 字
        snippet = page.body[:120].replace("\n", " ")
        results.append({
            "path": str(p.relative_to(root.root)).replace("\\", "/"),
            "kind": page.kind,
            "title": page.title,
            "score": score,
            "snippet": snippet,
        })
    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:limit]


# ---------- lint ----------

def lint(root: WikiRoot) -> list[dict]:
    """健康检查。返回 [{severity, category, message, path}]。"""
    issues: list[dict] = []
    all_names: dict[str, Path] = {}
    for p in root.iter_pages():
        all_names[slugify(p.stem)] = p
        # 也记录原始 stem 作为 key
        all_names[p.stem] = p

    index_names = {e["name"] for e in read_index_entries(root)}

    for p in root.iter_pages():
        page = read_page(root, p)
        rel = str(p.relative_to(root.root)).replace("\\", "/")

        # 1. broken wikilink（error）
        for link in page.wikilinks:
            key = slugify(link)
            if key not in all_names and link not in all_names:
                issues.append({
                    "severity": "error",
                    "category": "broken-link",
                    "message": f"指向不存在的页面: [[{link}]]",
                    "path": rel,
                })

        # 2. 缺失 frontmatter title（warning）
        if not page.frontmatter.get("title"):
            issues.append({
                "severity": "warning",
                "category": "missing-title",
                "message": "缺少 frontmatter title",
                "path": rel,
            })

        # 3. 未收入索引（warning，排除 sources 和 analysis 可选）
        if page.kind in ("entities", "concepts"):
            if page.name not in index_names and page.title not in index_names:
                issues.append({
                    "severity": "warning",
                    "category": "index-completeness",
                    "message": f"页面未收入 index.md: {page.name}",
                    "path": rel,
                })

    # 4. 孤儿页（无入站链接，warning）—— 简化：检查是否有任何页面引用它
    referenced: set[str] = set()
    for p in root.iter_pages():
        page = read_page(root, p)
        for link in page.wikilinks:
            referenced.add(slugify(link))
    for p in root.iter_pages():
        key = slugify(p.stem)
        rel = str(p.relative_to(root.root)).replace("\\", "/")
        in_index = p.stem in index_names or p.name in index_names
        if key not in referenced and not in_index:
            issues.append({
                "severity": "info",
                "category": "orphan-page",
                "message": "无入站链接且未收入索引",
                "path": rel,
            })

    return issues


def status(root: WikiRoot) -> dict:
    """wiki 统计。"""
    entities = len(list(root.dir("entities").glob("*.md"))) if root.dir("entities").is_dir() else 0
    concepts = len(list(root.dir("concepts").glob("*.md"))) if root.dir("concepts").is_dir() else 0
    sources = len(list(root.dir("sources").glob("*.md"))) if root.dir("sources").is_dir() else 0
    analysis = len(list(root.dir("analysis").glob("*.md"))) if root.dir("analysis").is_dir() else 0
    total = entities + concepts + sources + analysis
    return {
        "root": str(root.root),
        "entities": entities,
        "concepts": concepts,
        "sources": sources,
        "analysis": analysis,
        "total_pages": total,
    }

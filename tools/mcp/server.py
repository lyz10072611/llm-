"""llm-wiki MCP server。

提供一个 Model Context Protocol server，让外部 agent（Claude Desktop / Cursor / Trae 等）
通过 stdio 读写和维护这个 wiki。工具能力对齐 microsoft/llmwiki 的设计，但完全贴合
本仓库的目录结构（entities/concepts/sources/analysis 顶层）+ Obsidian `[[wikilink]]`。

启动：python tools/mcp/server.py --wiki-root <绝对路径>
"""
from __future__ import annotations

import argparse
from pathlib import Path

from mcp.server.mcpserver import MCPServer

from wiki import (
    CONTENT_DIRS,
    WikiRoot,
    Page,
    read_page,
    write_page,
    read_index_entries,
    upsert_index_entry,
    remove_index_entry,
    append_log,
    query,
    lint,
    status,
    slugify,
)


def _root_from_args() -> WikiRoot:
    parser = argparse.ArgumentParser(description="llm-wiki MCP server")
    parser.add_argument("--wiki-root", type=str, help="wiki 根目录绝对路径")
    args, _ = parser.parse_known_args()
    if args.wiki_root:
        root = Path(args.wiki_root)
    else:
        # 默认：本文件上三级（tools/mcp -> tools -> llm-wiki 根）
        root = Path(__file__).resolve().parent.parent.parent
    return WikiRoot(root=root.resolve())


wiki_root = _root_from_args()
mcp = MCPServer(
    "llm-wiki",
    instructions="""llm-wiki 个人知识库维护 MCP。目录结构：entities（实体/项目）、concepts（概念）、
sources（源摘要）、analysis（分析/地图）。页面用 YAML frontmatter（title 必填，tags/date/sources/related 可选）
+ Obsidian `[[wikilink]]` 双向链接。维护后可用 `python html-assets/build.py` 重新发布静态站点。""",
)


# ---------- 读工具 ----------

@mcp.tool()
def wiki_status() -> dict:
    """wiki 统计：各目录页数、总数、根路径。"""
    return status(wiki_root)


@mcp.tool()
def wiki_list_pages(kind: str | None = None) -> list[dict]:
    """列出所有 wiki 页（可按 kind 过滤：entities/concepts/sources/analysis）。返回 [{path,kind,title,tags}]。"""
    out = []
    for p in wiki_root.iter_pages():
        page = read_page(wiki_root, p)
        if kind and page.kind != kind:
            continue
        out.append({
            "path": str(p.relative_to(wiki_root.root)).replace("\\", "/"),
            "kind": page.kind,
            "title": page.title,
            "tags": page.frontmatter.get("tags", []),
        })
    return out


@mcp.tool()
def wiki_list_sources() -> list[dict]:
    """列出所有源文件页（sources/ 目录），含大小和修改日期。"""
    out = []
    for p in wiki_root.iter_sources():
        st = p.stat()
        page = read_page(wiki_root, p)
        out.append({
            "path": str(p.relative_to(wiki_root.root)).replace("\\", "/"),
            "title": page.title,
            "size": st.st_size,
            "modified": st.st_mtime,
        })
    return out


@mcp.tool()
def wiki_read_page(name: str) -> dict:
    """按短名/文件名读取一个页面，返回 frontmatter + 正文。name 如 'claude-mem' 或 'entities/claude-mem'。"""
    p = wiki_root.resolve(name)
    if not p:
        return {"error": f"找不到页面: {name}"}
    page = read_page(wiki_root, p)
    return {
        "path": str(p.relative_to(wiki_root.root)).replace("\\", "/"),
        "kind": page.kind,
        "frontmatter": page.frontmatter,
        "body": page.body,
        "wikilinks": page.wikilinks,
    }


@mcp.tool()
def wiki_query(q: str, limit: int = 20) -> list[dict]:
    """全文搜索：标题权重 > 正文，返回 [{path,kind,title,score,snippet}]。"""
    return query(wiki_root, q, limit)


@mcp.tool()
def wiki_lint(category: str | None = None) -> list[dict]:
    """健康检查：broken-link / missing-title / index-completeness / orphan-page。可按 category 过滤。"""
    issues = lint(wiki_root)
    if category:
        issues = [i for i in issues if i["category"] == category]
    return issues


@mcp.tool()
def wiki_read_index() -> list[dict]:
    """读取 index.md 所有条目 [{name, desc}]。"""
    return read_index_entries(wiki_root)


# ---------- 写工具 ----------

def _slug_related(related: list[str] | None) -> list[str] | None:
    """规范化 related 列表：每个元素去掉 [[ ]] 包装并 slugify，使其能 resolve 到文件名。"""
    if related is None:
        return None
    out = []
    for x in related:
        # 去掉可能的 [[ ]] 包装
        x = x.strip().strip("[").strip("]").strip()
        # 处理 [[name|display]] 形式，取 name 部分
        if "|" in x:
            x = x.split("|")[0].strip()
        s = slugify(x)
        if s:
            out.append(s)
    return out or None


def _ensure_frontmatter(fm: dict, title: str, kind: str) -> dict:
    if not fm.get("title"):
        fm["title"] = title
    return fm


@mcp.tool()
def wiki_write_page(kind: str, name: str, title: str, body: str, tags: list[str] | None = None,
                     related: list[str] | None = None) -> dict:
    """创建或覆盖一个页面。kind ∈ entities/concepts/sources/analysis。name 为文件名（不带扩展名）。"""
    if kind not in CONTENT_DIRS:
        return {"error": f"kind 必须是 {CONTENT_DIRS} 之一"}
    slug = slugify(name) or name
    path = wiki_root.dir(kind) / (slug + ".md")
    fm: dict = {"title": title}
    if tags:
        fm["tags"] = tags
    if related:
        fm["related"] = _slug_related(related)
    write_page(path, fm, body)
    # 自动更新索引（entities/concepts）
    if kind in ("entities", "concepts"):
        desc = body.strip().split("\n")[0][:80] if body.strip() else ""
        upsert_index_entry(wiki_root, slug, desc)
    return {"path": str(path.relative_to(wiki_root.root)).replace("\\", "/"), "created": True}


@mcp.tool()
def wiki_create_entity(name: str, title: str, body: str, tags: list[str] | None = None,
                       related: list[str] | None = None) -> dict:
    """创建实体页（entities/{name}.md）。"""
    return wiki_write_page("entities", name, title, body, tags, related)


@mcp.tool()
def wiki_create_concept(name: str, title: str, body: str, tags: list[str] | None = None,
                        related: list[str] | None = None) -> dict:
    """创建概念页（concepts/{name}.md）。"""
    return wiki_write_page("concepts", name, title, body, tags, related)


@mcp.tool()
def wiki_create_source(name: str, title: str, body: str, tags: list[str] | None = None,
                       sources: list[str] | None = None, related: list[str] | None = None) -> dict:
    """创建源摘要页（sources/src-{name}.md）。name 不含 src- 前缀。"""
    slug = slugify(name) or name
    if not slug.startswith("src-"):
        slug = "src-" + slug
    path = wiki_root.dir("sources") / (slug + ".md")
    fm: dict = {"title": title}
    if tags:
        fm["tags"] = tags
    if sources:
        fm["sources"] = sources
    if related:
        fm["related"] = _slug_related(related)
    write_page(path, fm, body)
    return {"path": str(path.relative_to(wiki_root.root)).replace("\\", "/"), "created": True}


@mcp.tool()
def wiki_create_analysis(name: str, title: str, body: str, tags: list[str] | None = None,
                         related: list[str] | None = None) -> dict:
    """创建分析页（analysis/{name}.md）。"""
    return wiki_write_page("analysis", name, title, body, tags, related)


@mcp.tool()
def wiki_update_page(name: str, body: str | None = None, title: str | None = None,
                     tags: list[str] | None = None, related: list[str] | None = None) -> dict:
    """局部更新一个已有页面：正文覆盖、或合并 title/tags/related。name 为短名。"""
    p = wiki_root.resolve(name)
    if not p:
        return {"error": f"找不到页面: {name}"}
    page = read_page(wiki_root, p)
    if body is not None:
        page.body = body
    if title is not None:
        page.frontmatter["title"] = title
    if tags is not None:
        page.frontmatter["tags"] = tags
    if related is not None:
        page.frontmatter["related"] = _slug_related(related)
    write_page(p, page.frontmatter, page.body)
    return {"path": str(p.relative_to(wiki_root.root)).replace("\\", "/"), "updated": True}


@mcp.tool()
def wiki_add_crosslinks(name: str, targets: list[str]) -> dict:
    """给页面添加 related 交叉链接（校验目标存在）。name 为当前页短名。"""
    p = wiki_root.resolve(name)
    if not p:
        return {"error": f"找不到页面: {name}"}
    # 规范化 targets（去 [[ ]]、slugify）
    targets = _slug_related(targets) or []
    missing = [t for t in targets if not wiki_root.resolve(t)]
    if missing:
        return {"error": f"目标页面不存在: {missing}"}
    page = read_page(wiki_root, p)
    existing = set(page.frontmatter.get("related", []))
    merged = list(existing) + [t for t in targets if t not in existing]
    page.frontmatter["related"] = merged
    write_page(p, page.frontmatter, page.body)
    return {"path": str(p.relative_to(wiki_root.root)).replace("\\", "/"), "related": merged}


@mcp.tool()
def wiki_update_index(name: str, desc: str) -> dict:
    """更新 index.md 中某个条目（name 为短名/标题，会自动 slugify）。"""
    slug = slugify(name) or name
    upsert_index_entry(wiki_root, slug, desc)
    return {"updated": slug}


@mcp.tool()
def wiki_append_log(verb: str, title: str, details: str = "") -> dict:
    """追加一条操作日志到 log.md。verb ∈ ingest/query/lint/update 等。"""
    append_log(wiki_root, verb, title, details)
    return {"appended": True, "verb": verb, "title": title}


@mcp.tool()
def wiki_resolve(name: str) -> dict:
    """解析短名到具体路径（用于调试 wikilink 是否命中）。"""
    p = wiki_root.resolve(name)
    if not p:
        return {"error": f"无法解析: {name}"}
    return {"path": str(p.relative_to(wiki_root.root)).replace("\\", "/")}


if __name__ == "__main__":
    mcp.run(transport="stdio")

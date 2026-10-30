"""命令行模拟 agent 验证 MCP 增量维护能力。

通过 MCP stdio client 真实调用 llm-wiki MCP server 的工具，跑通完整增量闭环：
读源 -> 创建实体/概念 -> wikilink 关联 -> 更新索引 -> 追加日志 -> 验证 lint/搜索。

使用 __mcp_demo__ 标记，验证后由 verify 脚本统一清理。
"""
import asyncio
import json
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

SERVER = StdioServerParameters(command="python", args=["server.py"])


async def main():
    async with stdio_client(SERVER) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            async def call(name, args):
                r = await session.call_tool(name, args)
                if r.is_error:
                    return {"__error__": r.content[0].text if r.content else "unknown"}
                # mcp 2.x 把 list 返回值展平成多个 content block，
                # 这里聚合：若多个 content 则合并成 list，单个则解析为对象。
                texts = [c.text for c in r.content if c.type == "text"]
                if not texts:
                    return {}
                if len(texts) == 1:
                    try:
                        return json.loads(texts[0])
                    except Exception:
                        return {"__raw__": texts[0]}
                # 多个 content：逐个解析，若都是 dict 则返回 list
                out = []
                for t in texts:
                    try:
                        out.append(json.loads(t))
                    except Exception:
                        out.append(t)
                return out

            print("=" * 60)
            print("[1] 初始状态")
            s = await call("wiki_status", {})
            print("    status:", json.dumps(s, ensure_ascii=False))

            print("=" * 60)
            print("[2] 读一个真实源（src-claude-mem-architecture）验证读工具")
            p = await call("wiki_read_page", {"name": "src-claude-mem-architecture"})
            print("    title:", p.get("frontmatter", {}).get("title"))
            print("    kind:", p.get("kind"))
            print("    body 前 60 字:", p.get("body", "")[:60].replace("\n", " "))

            print("=" * 60)
            print("[3] 增量：创建实体 __mcp-demo-entity__")
            r = await call("wiki_create_entity", {
                "name": "__mcp-demo-entity__",
                "title": "MCP 增量演示实体",
                "body": "这是一个命令行模拟 agent 创建的演示实体，用于验证 MCP 增量写入能力。\n\n它关联概念 [[__mcp-demo-concept__]]，构成一条增量关系。",
                "tags": ["mcp-demo", "test"],
                "related": ["__mcp-demo-concept__"],
            })
            print("    ", json.dumps(r, ensure_ascii=False))

            print("=" * 60)
            print("[4] 增量：创建概念 __mcp-demo-concept__")
            r = await call("wiki_create_concept", {
                "name": "__mcp-demo-concept__",
                "title": "MCP 增量演示概念",
                "body": "用于验证 MCP 增量维护的概念页。\n\n它被实体 [[__mcp-demo-entity__]] 引用，形成双向 wikilink。",
                "tags": ["mcp-demo", "concept"],
                "related": ["__mcp-demo-entity__"],
            })
            print("    ", json.dumps(r, ensure_ascii=False))

            print("=" * 60)
            print("[5] 增量：解析短名验证 wikilink 命中")
            r = await call("wiki_resolve", {"name": "__mcp-demo-entity__"})
            print("    resolve entity:", json.dumps(r, ensure_ascii=False))
            r = await call("wiki_resolve", {"name": "__mcp-demo-concept__"})
            print("    resolve concept:", json.dumps(r, ensure_ascii=False))

            print("=" * 60)
            print("[6] 增量：更新索引条目")
            r = await call("wiki_update_index", {
                "name": "__mcp-demo-entity__",
                "desc": "MCP 增量演示实体（命令行模拟）",
            })
            print("    ", json.dumps(r, ensure_ascii=False))

            print("=" * 60)
            print("[7] 增量：追加日志")
            r = await call("wiki_append_log", {
                "verb": "ingest",
                "title": "MCP 增量能力命令行模拟验证",
                "details": "通过 MCP stdio client 调用 7 类工具，跑通读源→建实体/概念→wikilink→更新索引→追加日志闭环。",
            })
            print("    ", json.dumps(r, ensure_ascii=False))

            print("=" * 60)
            print("[8] 验证：搜索能命中新内容")
            r = await call("wiki_query", {"q": "mcp 增量演示", "limit": 5})
            for item in r:
                print("    -", item["path"], "score=", item["score"])

            print("=" * 60)
            print("[9] 验证：lint 检查新页面（应无 broken-link）")
            r = await call("wiki_lint", {"category": "broken-link"})
            demo_broken = [i for i in r if "__mcp-demo" in i["path"]]
            print("    演示页 broken-link 数:", len(demo_broken))
            if demo_broken:
                for i in demo_broken:
                    print("      ", i["path"], "->", i["message"])

            print("=" * 60)
            print("[10] 最终状态")
            s = await call("wiki_status", {})
            print("    status:", json.dumps(s, ensure_ascii=False))

            print()
            print("✅ 增量闭环验证完成")


if __name__ == "__main__":
    asyncio.run(main())

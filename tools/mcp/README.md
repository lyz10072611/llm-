# llm-wiki MCP Server

个人知识库 `llm-wiki` 的 MCP（Model Context Protocol）server，让外部 agent（Claude Desktop / Cursor / Trae 等）通过 stdio 读写和维护 wiki。工具能力对齐 microsoft/llmwiki 的设计，但完全贴合本仓库的目录结构与 `[[wikilink]]` 约定。

## 目录结构约定

wiki 根目录（即 `llm-wiki/` 顶层）下有四个内容目录：

| 目录 | 含义 | 命名示例 |
|------|------|----------|
| `entities/` | 实体/项目/工具 | `claude-mem.md`、`kubernetes.md` |
| `concepts/` | 概念/方法/模式 | `agent-memory.md`、`paged-attention.md` |
| `sources/` | 源摘要页 | `src-claude-mem-architecture.md` |
| `analysis/` | 分析/项目地图/选型矩阵 | `agent-memory-project-map.md` |

页面格式：YAML frontmatter（`title` 必填，`tags`/`date`/`sources`/`related` 可选）+ 正文，正文用 Obsidian `[[wikilink]]` 做双向链接（`[[name]]` 或 `[[name|显示名]]`）。

## 安装

```bash
pip install -r tools/mcp/requirements.txt
# 或直接
pip install "mcp>=2.0.0"
```

## 本地运行

```bash
# 默认自动定位到 llm-wiki 根目录（推荐）
python tools/mcp/server.py

# 或显式指定 wiki 根目录
python tools/mcp/server.py --wiki-root "C:\Users\yongze.lv\Desktop\知识沉淀\llm-wiki"
```

## 接入 MCP 客户端

### Claude Desktop

编辑 `claude_desktop_config.json`：

```jsonc
{
  "mcpServers": {
    "llm-wiki": {
      "command": "python",
      "args": ["C:\\Users\\yongze.lv\\Desktop\\知识沉淀\\llm-wiki\\tools\\mcp\\server.py"]
    }
  }
}
```

### Cursor

编辑 `~/.cursor/mcp.json`：

```jsonc
{
  "mcpServers": {
    "llm-wiki": {
      "command": "python",
      "args": ["C:\\Users\\yongze.lv\\Desktop\\知识沉淀\\llm-wiki\\tools\\mcp\\server.py"]
    }
  }
}
```

### Trae / 其他支持 MCP 的客户端

在对应客户端的 MCP 配置里添加同样的 `command` + `args`，`command` 为 `python`，`args` 指向 `server.py` 的绝对路径。

## 可用工具

### 读工具

| 工具 | 说明 |
|------|------|
| `wiki_status` | wiki 统计（各目录页数、总数、根路径） |
| `wiki_list_pages` | 列出所有页面（可按 kind 过滤） |
| `wiki_list_sources` | 列出源文件页（含大小/日期） |
| `wiki_read_page` | 按短名读单页（frontmatter + body + wikilinks） |
| `wiki_query` | 全文搜索（标题权重 > 正文） |
| `wiki_lint` | 健康检查（broken-link / missing-title / index-completeness / orphan-page） |
| `wiki_read_index` | 读 index.md 所有条目 |
| `wiki_resolve` | 解析短名到具体路径（调试 wikilink） |

### 写工具

| 工具 | 说明 |
|------|------|
| `wiki_write_page` | 创建/覆盖页面（任意 kind） |
| `wiki_create_entity` | 创建实体页 |
| `wiki_create_concept` | 创建概念页 |
| `wiki_create_source` | 创建源摘要页（自动加 `src-` 前缀） |
| `wiki_create_analysis` | 创建分析页 |
| `wiki_update_page` | 局部更新（body/title/tags/related） |
| `wiki_add_crosslinks` | 添加 related 交叉链接（校验目标存在） |
| `wiki_update_index` | 更新 index.md 条目 |
| `wiki_append_log` | 追加操作日志 |

## 发布静态站点

维护完内容后，用 Python 脚本重新生成 HTML 静态站点：

```bash
python html-assets/build.py            # 幂等构建
python html-assets/build.py --force    # 强制覆盖手写 HTML
python html-assets/build.py --pdf-topics   # 导出各主题 PDF
```

## 与 microsoft/llmwiki 的差异

| 维度 | microsoft/llmwiki | 本项目 |
|------|-------------------|--------|
| 目录结构 | `.wiki/wiki/{entities,concepts,sources}` | 顶层 `{entities,concepts,sources,analysis}` |
| 链接 | 标准 `[T](path.md)` | Obsidian `[[wikilink]]` |
| 实现 | TypeScript（VS Code 扩展 + npm 包） | Python（MCP server + build.py） |
| 发布 | 无（纯 VS Code 内） | build.py 生成 HTML 静态站点 |

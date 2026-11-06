from __future__ import annotations

import asyncio
import json
import re
from typing import Any

from knowledge_base.infrastructure.llm import (
    build_source_blocks,
    call_anthropic_json,
    call_anthropic_text,
    require_settings,
)
from knowledge_base.infrastructure.settings import Settings


_HASH_HEADING_RE = re.compile(r"^(#{1,6})\s+\S.*$")
_BOLD_HEADING_RE = re.compile(r"^\*\*([^*]+)\*\*\s*$")
_BOLD_LABEL_BOUNDARY_RE = re.compile(r"^\*\*([^*\n]+)\*\*\s*[:：]\s*\S.*$")
_CHINESE_TOP_LEVEL_RE = re.compile(r"^[一二三四五六七八九十百千万零〇两]+[、.．]")
_NUMERIC_HEADING_RE = re.compile(r"^(\d+(?:\.\d+)*)")


def _markdown_heading_level(line: str) -> int | None:
    stripped = line.strip()
    hash_match = _HASH_HEADING_RE.match(stripped)
    if hash_match:
        return len(hash_match.group(1))
    bold_match = _BOLD_HEADING_RE.match(stripped)
    if not bold_match:
        return None
    title = bold_match.group(1).strip()
    numeric_match = _NUMERIC_HEADING_RE.match(title)
    if numeric_match:
        return min(numeric_match.group(1).count(".") + 1, 6)
    if _CHINESE_TOP_LEVEL_RE.match(title):
        return 1
    return 2


def _hash_heading_level(line: str) -> int | None:
    match = _HASH_HEADING_RE.match(str(line or "").strip())
    if not match:
        return None
    return len(match.group(1))


def _is_bold_label_boundary(line: str) -> bool:
    return _BOLD_LABEL_BOUNDARY_RE.match(str(line or "").strip()) is not None


def _extract_markdown_headings(markdown_text: str) -> list[str]:
    headings: list[str] = []
    for line in str(markdown_text or "").splitlines():
        if _markdown_heading_level(line) is not None:
            headings.append(line.strip())
    return headings


def _find_markdown_section_range(lines: list[str], target_heading: str) -> tuple[int, int]:
    normalized_target = str(target_heading or "").strip()
    if not normalized_target:
        raise ValueError("补丁操作缺少 target_heading")
    start_index = -1
    target_level: int | None = None
    for index, line in enumerate(lines):
        if line.strip() != normalized_target:
            continue
        target_level = _markdown_heading_level(line)
        if target_level is None:
            raise ValueError(f"target_heading 不是可识别的 Markdown 标题: {normalized_target}")
        start_index = index
        break
    if start_index < 0 or target_level is None:
        raise ValueError(f"未在基线 Markdown 中找到标题: {normalized_target}")

    end_index = len(lines)
    target_hash_level = _hash_heading_level(lines[start_index])
    target_is_bold_heading = _BOLD_HEADING_RE.match(lines[start_index].strip()) is not None
    bold_label_boundary_enabled: bool | None = None
    for index in range(start_index + 1, len(lines)):
        hash_level = _hash_heading_level(lines[index])
        if target_hash_level is not None:
            if hash_level is not None and hash_level <= target_hash_level:
                end_index = index
                break
            continue
        if target_is_bold_heading:
            if _is_bold_label_boundary(lines[index]):
                if bold_label_boundary_enabled:
                    end_index = index
                    break
                if bold_label_boundary_enabled is None:
                    bold_label_boundary_enabled = False
            elif lines[index].strip() and bold_label_boundary_enabled is None:
                bold_label_boundary_enabled = True
        heading_level = _markdown_heading_level(lines[index])
        if heading_level is not None and (hash_level is not None or heading_level <= target_level):
            end_index = index
            break
    return start_index, end_index


def _normalize_patch_content(content: Any) -> str:
    normalized = str(content or "").strip()
    if not normalized:
        raise ValueError("补丁操作 content 不能为空")
    return normalized


def _section_end_from_heading_index(lines: list[str], heading_index: int, boundary_end: int) -> int:
    heading_level = _markdown_heading_level(lines[heading_index])
    if heading_level is None:
        return heading_index + 1
    heading_is_hash = _hash_heading_level(lines[heading_index]) is not None
    heading_is_bold = _BOLD_HEADING_RE.match(lines[heading_index].strip()) is not None
    bold_label_boundary_enabled: bool | None = None
    for index in range(heading_index + 1, boundary_end):
        next_hash_level = _hash_heading_level(lines[index])
        if heading_is_bold:
            if _is_bold_label_boundary(lines[index]):
                if bold_label_boundary_enabled:
                    return index
                if bold_label_boundary_enabled is None:
                    bold_label_boundary_enabled = False
            elif lines[index].strip() and bold_label_boundary_enabled is None:
                bold_label_boundary_enabled = True
        next_heading_level = _markdown_heading_level(lines[index])
        if next_heading_level is None:
            continue
        if heading_is_hash:
            if next_hash_level is not None and next_hash_level <= heading_level:
                return index
            continue
        if next_hash_level is not None or next_heading_level <= heading_level:
            return index
    return boundary_end


def _replace_existing_child_span_for_append(
    *,
    lines: list[str],
    start_index: int,
    end_index: int,
    content: str,
) -> str | None:
    content_lines = content.splitlines()
    content_headings = [
        line.strip()
        for line in content_lines
        if _markdown_heading_level(line) is not None
    ]
    if not content_headings:
        return None
    first_heading = content_headings[0]
    last_heading = content_headings[-1]

    first_matches = [
        index
        for index in range(start_index + 1, end_index)
        if lines[index].strip() == first_heading
    ]
    if not first_matches:
        return None
    replace_start = first_matches[0]
    last_matches = [
        index
        for index in range(replace_start, end_index)
        if lines[index].strip() == last_heading
    ]
    if not last_matches:
        return None
    replace_end = _section_end_from_heading_index(lines, last_matches[-1], end_index)
    replacement = f"{content.rstrip()}\n\n"
    return "".join([*lines[:replace_start], replacement, *lines[replace_end:]]).strip()


def _apply_brand_knowledge_patch_operations(
    *,
    base_markdown: str,
    operations: list[dict[str, Any]],
) -> str:
    merged = str(base_markdown or "").strip()
    if not merged:
        raise ValueError("base_markdown 不能为空")
    if not operations:
        return merged

    for operation in operations:
        if not isinstance(operation, dict):
            raise ValueError("补丁操作必须是 JSON 对象")
        operation_type = str(operation.get("op") or operation.get("type") or "").strip()

        if operation_type in {"replace_section", "append_to_section", "insert_after_section", "delete_section"}:
            target_heading = str(
                operation.get("target_heading")
                or operation.get("section_heading")
                or operation.get("section_title")
                or ""
            ).strip()
            lines = merged.splitlines(keepends=True)
            start_index, end_index = _find_markdown_section_range(lines, target_heading)
            if operation_type == "delete_section":
                merged = "".join([*lines[:start_index], *lines[end_index:]]).strip()
                continue

            content = _normalize_patch_content(operation.get("content"))
            if operation_type == "replace_section":
                if content.splitlines()[0].strip() != target_heading:
                    content = f"{target_heading}\n\n{content}"
                replacement = f"{content.rstrip()}\n\n"
                merged = "".join([*lines[:start_index], replacement, *lines[end_index:]]).strip()
                continue

            insert_index = end_index if operation_type == "append_to_section" else end_index
            if operation_type == "append_to_section":
                replaced = _replace_existing_child_span_for_append(
                    lines=lines,
                    start_index=start_index,
                    end_index=end_index,
                    content=content,
                )
                if replaced is not None:
                    merged = replaced
                    continue
            before = "".join(lines[:insert_index]).rstrip()
            after = "".join(lines[insert_index:]).lstrip("\n")
            merged = f"{before}\n\n{content.rstrip()}\n\n{after}".strip()
            continue

        if operation_type == "append_document":
            content = _normalize_patch_content(operation.get("content"))
            merged = f"{merged.rstrip()}\n\n{content.rstrip()}".strip()
            continue

        raise ValueError(f"不支持的知识库补丁操作: {operation_type}")

    return merged.strip()


async def scan_brand_knowledge_conflicts(
    *,
    brand_name: str,
    markdown_sources: list[dict[str, Any]],
    settings: Settings | None = None,
) -> dict[str, Any]:
    resolved_settings = require_settings(settings)
    if not markdown_sources:
        raise ValueError("markdown_sources 不能为空")

    source_blocks = build_source_blocks(
        markdown_sources,
        include_full_markdown=True,
    )

    prompt = f"""
你是品牌资料冲突扫描助手。你的任务是先对所有源 markdown 文件做一次完整的冲突盘点，并且只把“真正需要人来裁决的硬冲突”上报给用户。

品牌名称：
{brand_name}

> 说明：本 prompt 适用于**任意行业、任意品牌**的资料整合。下文出现的所有具体例子（网址、地名、字段名、行业属性等）仅用于说明判定规则，**不代表你处理的品牌一定具备这些字段或行业特征**；请按当前品牌真实资料灵活套用，不要把示例当成必备项或行业约束。

## 一、阅读要求
1. 你必须逐个完整阅读所有 source markdown 文件，不抽样、不跳读、不只看标题。表格、清单、资质荣誉、新闻、FAQ、补充说明等各类内容都要读全，避免漏行、漏项。
2. 这是“首轮一次性全量扫描”。凡是真正的硬冲突，必须在本次一并列出，不允许只返回一个代表性冲突，也不要边扫边假设后续会再补。

## 二、来源角色主次规则（用于自动消解，不制造冲突）
如果 source markdown 文件里带有“来源角色”，请严格按下面规则处理：
1. `attachment_asset` 是主来源。它代表附件原文，是本轮冲突扫描的主依据。
2. `external_enrichment` 是补充来源。它只用于补充、校验、提示疑点，不能推翻附件原文。
3. 若 `external_enrichment` 与 `attachment_asset` 冲突：
   - 一律以 `attachment_asset` 为准；
   - 不要把这类差异上报到 conflicts；
   - 应登记到 auto_merged，说明“附件优先，补充来源不覆盖附件”。
4. 若 `external_enrichment` 只是补充了附件里没有的信息，不算冲突。
5. 若多个 `external_enrichment` 之间互相差异，但没有与附件原文形成必须人工裁决的矛盾，也不要上报到 conflicts。

## 三、数据源权威优先级（用于自动消解，不制造冲突）
不同来源的可信度不同。当差异只是“同一事实、不同权威度的写法”时，直接采信高优先级来源，不要上报为冲突：
1. 工商/官方登记类（如工商结构化基线、营业执照、官网备案信息）——对“公司注册主体、注册资本、法定代表人、参保人数、成立日期、注册地址”等法定事实，优先级最高。
2. 官方语料库 / 品牌方结构化知识——对“品牌定位、价值主张、产品参数”等品牌自述事实，优先级次之。
3. 营销/宣传/FAQ/竞品对比等话术类——对法定事实不具权威性，只作语气与卖点参考。
说明：对法定事实，若高权威来源已明确给出，则以它为准，营销话术的差异不算冲突。

## 四、判定流程：先分类，再决定是否上报
对每一处差异，先归入下面四类之一，只有第 (D) 类才写进 conflicts：

(A) 纯格式/等价差异 —— 同一事实的不同写法。例如：网址带不带 http:// 或结尾斜杠、全角半角标点、大小写、单位写法、明显同义。
    处理：静默归一化，不上报，不记录。

(B) 可取并集 / 可共存 / 不同粒度 —— 两处并不矛盾，可同时成立或合并。例如（跨行业通用示例）：
    - 一处列举的清单是另一处的子集（如别名、经营范围、荣誉列表）→ 取并集；
    - 一处是大范围、另一处是其所含的小范围（大范围已包含小范围）→ 不矛盾；
    - 同一事项的“一句话简述” vs “长段落详述”（不同表述粒度）→ 可并存；
    - 同一属性/能力被本品牌与某竞品各自具备 → 各自成立，非归属冲突。
    处理：不上报到 conflicts，但登记到 auto_merged 数组，说明合并/共存方式，供整合阶段直接采用。

(C) 高权威来源可直接裁决 —— 依据第二节和第三节优先级，法定事实以高权威来源为准；附件与补充来源冲突时，以附件为准。
    处理：不上报到 conflicts，登记到 auto_merged，注明采信来源与理由。

(D) 真·硬冲突 —— 对同一事项存在实质矛盾，且无法用 (A)(B)(C) 消解，若不问用户就无法确定最终该写哪个。典型：同一法定事实两个权威来源互相打架、同一参数两个数值互斥且都可能对外使用。
    处理：写进 conflicts。

## 五、去重与合并
1. 同一根因不要拆成多条。若多处差异其实源自同一个事实分歧（例如某个核心归属/主体分歧会连带影响总部、供应链、服务范围、对外表述等多个位置），应合并为一条冲突，在 description 里列出受影响的所有位置，不要按出现位置拆成 C01/C03/… 多条。
2. 每条冲突用 severity 标注：hard=必须用户裁决；mergeable=可合并但仍列出供知晓；format=纯格式。正常情况下 conflicts 里应以 hard 为主。

## 六、时间演进
若原文明确给出时间演进证据（如带日期的里程碑），按事实演进理解，不算冲突；只有在无任何时间证据、且两个口径实质互斥时，才作为硬冲突上报。

## 七、输出
- 不要生成最终品牌知识库，不要输出 final_markdown。
- 如果没有任何 (D) 类硬冲突，status 返回 no_conflicts；否则返回 waiting_user_input。
- conflicts 只放需要用户裁决的项（以 hard 为主）；被自动消解的差异放进 auto_merged（供整合阶段使用，不打扰用户）。
- 尤其注意：凡是“附件原文 vs 外部回补补充”的差异，只要附件原文已经明确，就默认按附件优先自动消解，不要抛给用户。

源 markdown 文件：
{chr(10).join(source_blocks)}

请严格输出一个 JSON 对象，不要输出解释文字，不要输出代码块。
输出格式：
{{
  "status": "waiting_user_input" | "no_conflicts",
  "scan_summary": "已完成 x 份文件全量扫描：上报 x 条需裁决硬冲突，自动消解 x 条（格式/可合并/权威优先）。",
  "conflicts": [
    {{
      "conflict_id": "",
      "topic": "冲突主题",
      "severity": "hard",
      "description": "冲突说明；如为同一根因牵连多处，请在此列出受影响的所有位置",
      "options": [
        {{
          "option_id": "A",
          "content": "候选内容",
          "source_files": ["来源1.md"]
        }}
      ]
    }}
  ],
  "auto_merged": [
    {{
      "topic": "已自动消解的差异主题",
      "category": "format | mergeable | authority",
      "resolution": "采用的合并/归一化/采信结果及理由",
      "source_files": ["来源1.md", "来源2.md"]
    }}
  ]
}}
""".strip()

    return await asyncio.to_thread(call_anthropic_json, prompt, settings=resolved_settings)


async def generate_brand_knowledge_round(
    *,
    brand_name: str,
    markdown_sources: list[dict[str, Any]],
    base_knowledge_markdown: str | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    resolved_settings = require_settings(settings)
    if not markdown_sources:
        raise ValueError("markdown_sources 不能为空")

    source_blocks = build_source_blocks(
        markdown_sources,
        include_full_markdown=True,
    )
    base_markdown_block = (base_knowledge_markdown or "").strip()

    prompt = f"""
你是品牌 AI 知识库更新助手。请基于“上一版全量品牌 AI 知识库基线”和“本次确认后的附件 Markdown及相关补充附件资料 Markdown”，生成新版完整《品牌AI知识库》Markdown 正文。

品牌名称：
{brand_name}

更新规则：
1. “上一版全量品牌 AI 知识库基线”是上一版完整知识库底本；你必须以它为主体，基于“本次确认后的附件 Markdown及相关补充附件资料 Markdown”完成增量融合。
2. 内容以“本次确认后的附件 Markdown”为主：当附件内容与基线就同一事项存在不同表述时，采用附件的口径，覆盖基线中的旧表述，不要并列保留冲突版本。
3. “相关补充附件资料 Markdown”仅用于补充本次确认附件中没有、且与其不冲突的信息；若与“本次确认后的附件 Markdown”冲突，以“本次确认后的附件 Markdown”为准。
4. 附件及补充资料未覆盖的事项，继续沿用基线中仍然有效的内容；未提及某主题，不代表要删除基线中该主题的有效内容。
5. 你只能做内容整合与结构重组，可以为了便于阅读和检索调整顺序，但不得私自修改原始内容的措辞、数字、结论和表述口径（“以附件为准”的覆盖除外）。
6. 去重逻辑：仅当出现“明显重复的同一语句或同一事实声明”时才去重；只去重复、不去信息；若措辞略有差异但事实一致，优先保留信息更完整的版本；若差异可能影响理解、归属或事实口径，则不得按重复处理。
7. 按“信息维度”归类，而不是按文件归类；把内容归入统一、结构化、便于检索的知识库骨架，骨架由资料内容驱动。
8. 不得编造基线与附件中都没有的新事实。
9. 不得扫描或假设 OSS converted 目录下的其他文件；只能使用本 prompt 中提供的基线与附件内容。
10. 输出必须是完整《品牌AI知识库》Markdown 正文，不要输出 JSON、解释文字或代码块围栏。
11. 输出前请自行检查：章节基本齐全、无残留占位符、未引入基线与附件中不存在的新事实、重要清单或表格项无明显遗漏。

上一版全量品牌 AI 知识库基线：
```markdown
{base_markdown_block or "无"}
```

本次确认后的附件 Markdown及相关补充附件资料 Markdown：
{chr(10).join(source_blocks)}

请直接输出新版完整 Markdown 正文。
""".strip()
    
    final_markdown = await asyncio.to_thread(call_anthropic_text, prompt, settings=resolved_settings)
    normalized_markdown = str(final_markdown or "").strip()
    if not normalized_markdown:
        raise ValueError("Claude 未返回有效的品牌知识库 Markdown")
    return {
        "status": "completed",
        "conflicts": [],
        "conflict_markdown": "",
        "final_markdown": normalized_markdown,
    }


async def generate_brand_knowledge_patch_markdown(
    *,
    brand_name: str,
    markdown_sources: list[dict[str, Any]],
    base_knowledge_markdown: str,
    history_resolutions: list[dict[str, Any]] | None = None,
    current_resolutions: list[dict[str, Any]] | None = None,
    auto_merged: list[dict[str, Any]] | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    resolved_settings = require_settings(settings)
    if not markdown_sources:
        raise ValueError("markdown_sources 不能为空")
    base_markdown_block = str(base_knowledge_markdown or "").strip()
    if not base_markdown_block:
        raise ValueError("base_knowledge_markdown 不能为空")

    source_blocks = build_source_blocks(
        markdown_sources,
        include_full_markdown=True,
    )
    base_headings = _extract_markdown_headings(base_markdown_block)

    prompt = f"""
你是品牌 AI 知识库补丁更新助手。请基于“上一版全量品牌 AI 知识库基线”和“本次更新来源”，只生成局部补丁操作 JSON；不要输出新版完整 Markdown。

品牌名称：
{brand_name}

核心目标：
1. 上一版基线是最终文档底稿。未被本次资料明确覆盖、替换、删除或追加的内容，必须由系统原样保留。
2. 你的输出只能描述需要变更的局部章节或追加内容，严禁整篇重写。
3. 如果本次资料只影响少数章节，只返回这些章节的补丁；不要触碰无关章节。
4. target_heading 必须逐字复制“基线可用标题列表”中的某一行。找不到合适标题但确需新增内容时，使用 append_document。
5. replace_section 的 content 必须包含完整目标标题行以及该章节的新完整正文；append_to_section / insert_after_section / append_document 的 content 只写新增片段。
6. 不得编造基线与本次资料都没有的新事实。
7. 历史已确认决策、本轮新增决策和自动消解决议都必须落地到补丁中；未选中的冲突口径不要保留。
8. 如果“本次更新来源”明确要求删除、移除、不要保留某类内容，必须使用 delete_section 删除对应小节，或使用 replace_section 输出删除后的完整父章节；严禁用 append_to_section 追加一个删减版片段来表达删除。
9. 对“来源角色：iteration_web_article”的网页正文，尤其是用户要求“增加官方报道文章/报道链接/新闻文章”时，补丁中应保留标题、来源链接、发布时间、正文主要小标题和关键段落；不要压缩成一句话摘要。可以去除导航、页脚、广告等噪声，但不得丢弃正文里的核心事实链条。
10. replace_section 只替换目标小节本身；如果目标小节后紧跟“**字段名**:正文”或“**字段名**：正文”形式的独立说明，且本轮没有明确要求删除，不得移除该相邻说明。

允许的操作类型：
- replace_section：替换 target_heading 对应的整个章节，直到下一个同级或更高级标题之前。
- append_to_section：把 content 追加到 target_heading 对应章节末尾。
- insert_after_section：把 content 插入到 target_heading 对应章节之后。
- append_document：把 content 追加到文档末尾，仅用于基线没有合适标题的新主题。
- delete_section：删除 target_heading 对应的整个章节，仅用于本次资料明确要求删除该主题；content 可为空。

基线可用标题列表：
{json.dumps(base_headings, ensure_ascii=False)}

历史已确认决策：
{json.dumps(history_resolutions or [], ensure_ascii=False)}

本轮新增决策：
{json.dumps(current_resolutions or [], ensure_ascii=False)}

扫描阶段已自动消解的差异：
{json.dumps(auto_merged or [], ensure_ascii=False)}

上一版全量品牌 AI 知识库基线：
```markdown
{base_markdown_block}
```

本次更新来源：
{chr(10).join(source_blocks)}

请严格输出一个 JSON 对象，不要输出解释文字，不要输出代码块。
输出格式：
{{
  "status": "completed",
  "summary": "一句话说明本次补丁更新了哪些章节；如果无需修改，说明无需修改",
  "operations": [
    {{
      "op": "replace_section | append_to_section | insert_after_section | append_document | delete_section",
      "target_heading": "append_document 可为空，其它操作必须填基线标题原文",
      "content": "delete_section 可为空；其它操作必须填写补丁 Markdown 内容"
    }}
  ]
}}
""".strip()

    patch_payload = await asyncio.to_thread(call_anthropic_json, prompt, settings=resolved_settings)
    operations = patch_payload.get("operations")
    if operations is None:
        operations = []
    if not isinstance(operations, list):
        raise ValueError("Claude 返回的补丁 operations 不是数组")
    normalized_operations = [operation for operation in operations if isinstance(operation, dict)]
    if len(normalized_operations) != len(operations):
        raise ValueError("Claude 返回的补丁 operations 包含非对象项")
    final_markdown = _apply_brand_knowledge_patch_operations(
        base_markdown=base_markdown_block,
        operations=normalized_operations,
    )
    if not final_markdown:
        raise ValueError("补丁合并后未生成有效的品牌知识库 Markdown")
    return {
        "status": "completed",
        "conflicts": [],
        "conflict_markdown": "",
        "final_markdown": final_markdown,
        "patch_summary": str(patch_payload.get("summary") or "").strip(),
        "patch_operations": normalized_operations,
    }


async def generate_brand_ai_knowledge_patch_from_structured_update(
    *,
    brand_name: str,
    previous_ai_knowledge_markdown: str,
    structured_knowledge_markdown: str,
    knowledge_revision: str = "",
    deleted_sections: list[str] | None = None,
    update_reason: str = "knowledge_update",
    settings: Settings | None = None,
) -> dict[str, Any]:
    resolved_settings = require_settings(settings)
    previous_markdown_block = str(previous_ai_knowledge_markdown or "").strip()
    normalized_structured_markdown = str(structured_knowledge_markdown or "").strip()
    if not previous_markdown_block:
        raise ValueError("previous_ai_knowledge_markdown 不能为空")
    if not normalized_structured_markdown:
        raise ValueError("structured_knowledge_markdown 不能为空")

    base_headings = _extract_markdown_headings(previous_markdown_block)
    deleted_sections_prompt = json.dumps(deleted_sections or [], ensure_ascii=False)

    prompt = f"""
你是品牌 AI 知识库结构化更新补丁助手。请基于“上一版全量品牌 AI 知识库基线”和“本次 /knowledge/update 结构化变更摘要”，只生成局部补丁操作 JSON；不要输出新版完整 Markdown。

品牌名称：
{brand_name}

知识库版本：
{knowledge_revision or "未提供"}

更新原因：
{update_reason or "knowledge_update"}

本次明确删除或收缩的结构化 section：
{deleted_sections_prompt}

核心目标：
1. 上一版基线是最终文档底稿。未被本次结构化变更明确覆盖、替换、删除或追加的内容，必须由系统原样保留。
2. 你的输出只能描述需要变更的局部章节或追加内容，严禁整篇重写。
3. “本次 /knowledge/update 结构化变更摘要”优先级最高；如果它与基线冲突，采用本次更新后的内容。
4. 未出现在本次变更摘要中的章节、字段、表格行、列表项，不代表删除，不要触碰。
5. target_heading 必须逐字复制“基线可用标题列表”中的某一行。找不到合适标题但确需新增内容时，使用 append_document。
6. replace_section 的 content 必须包含完整目标标题行以及该章节的新完整正文；append_to_section / insert_after_section / append_document 的 content 只写新增片段。
7. 只有“本次明确删除或收缩的结构化 section”或变更摘要里的删除语义明确要求移除时，才允许使用 delete_section 或在 replace_section 中移除旧内容。
8. 不得编造基线与本次结构化变更都没有的新事实。
9. replace_section 只替换目标小节本身；如果目标小节后紧跟“**字段名**:正文”或“**字段名**：正文”形式的独立说明，且本次结构化变更没有明确要求删除，不得移除该相邻说明。

允许的操作类型：
- replace_section：替换 target_heading 对应的整个章节，直到下一个同级或更高级标题之前。
- append_to_section：把 content 追加到 target_heading 对应章节末尾。
- insert_after_section：把 content 插入到 target_heading 对应章节之后。
- append_document：把 content 追加到文档末尾，仅用于基线没有合适标题的新主题。
- delete_section：删除 target_heading 对应的整个章节，仅用于本次明确删除且该章节不应保留任何有效内容。

基线可用标题列表：
{json.dumps(base_headings, ensure_ascii=False)}

上一版全量品牌 AI 知识库基线：
```markdown
{previous_markdown_block}
```

本次 /knowledge/update 结构化变更摘要：
```markdown
{normalized_structured_markdown}
```

请严格输出一个 JSON 对象，不要输出解释文字，不要输出代码块。
输出格式：
{{
  "status": "completed",
  "summary": "一句话说明本次补丁更新了哪些章节；如果无需修改，说明无需修改",
  "operations": [
    {{
      "op": "replace_section | append_to_section | insert_after_section | append_document | delete_section",
      "target_heading": "append_document 可为空，其它操作必须填基线标题原文",
      "content": "delete_section 可为空；其它操作必须填写补丁 Markdown 内容"
    }}
  ]
}}
""".strip()

    patch_payload = await asyncio.to_thread(call_anthropic_json, prompt, settings=resolved_settings)
    operations = patch_payload.get("operations")
    if operations is None:
        operations = []
    if not isinstance(operations, list):
        raise ValueError("Claude 返回的结构化更新补丁 operations 不是数组")
    normalized_operations = [operation for operation in operations if isinstance(operation, dict)]
    if len(normalized_operations) != len(operations):
        raise ValueError("Claude 返回的结构化更新补丁 operations 包含非对象项")
    final_markdown = _apply_brand_knowledge_patch_operations(
        base_markdown=previous_markdown_block,
        operations=normalized_operations,
    )
    if not final_markdown:
        raise ValueError("结构化更新补丁合并后未生成有效的品牌知识库 Markdown")
    return {
        "status": "completed",
        "conflicts": [],
        "conflict_markdown": "",
        "final_markdown": final_markdown,
        "patch_summary": str(patch_payload.get("summary") or "").strip(),
        "patch_operations": normalized_operations,
    }


async def generate_brand_knowledge_full_markdown(
    *,
    brand_name: str,
    markdown_sources: list[dict[str, Any]],
    history_resolutions: list[dict[str, Any]],
    current_resolutions: list[dict[str, Any]],
    auto_merged: list[dict[str, Any]] | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    resolved_settings = require_settings(settings)
    if not markdown_sources:
        raise ValueError("markdown_sources 不能为空")

    source_blocks = build_source_blocks(
        markdown_sources,
        include_full_markdown=True,
    )

    prompt = f"""
你是品牌知识库整编助手。冲突扫描已完成。请基于全部源 markdown 文件、历史已确认决策、本轮新增决策与扫描阶段已自动消解的差异，整合出一份**完整、忠实、便于阅读与检索**的最终《品牌AI知识库》Markdown 正文。这份文档的定位是"无损归档 + 结构重排 + 落地已确认裁定"，不是"摘要"——宁可长、不可漏；并且它是最终下载稿，正文中不得再出现任何待确认标记。

品牌名称：
{brand_name}

> 说明：本 prompt 适用于**任意行业、任意品牌**。下文示例（字段名、行业属性、数量等）仅用于说明规则，不代表当前品牌一定具备；请按其真实资料灵活套用，章节与字段完全由资料内容驱动，不要套用示例中的行业特征。

## 一、最高原则：只整合、不改写、不压缩
1. 必须完整阅读所有源 markdown 文件，不得抽样、不得跳读。各类内容——表格、清单、资质荣誉、新闻链接、FAQ、术语、话术、参数、说明等——全部要落进正文。
2. 你只能做"内容整合 + 归类 + 重排顺序"。**严禁改写、缩写、意译、概括任何原始内容**：
   - FAQ / 问答类必须逐条保留"完整问题 + 完整回答"原文，禁止把答案压成一句话；
   - 产品/服务描述、术语解释、宣传要点等，都要保留原始整段文字，不得提炼成要点缩写；

## 二、骨架：优先复用"字段表型"源文件作为主干
1. 若源文件中存在"品牌知识库/字段表"型文件（含 核心维度 / 字段名称 / 具体内容 这类结构），**以它的字段结构为主骨架基础**，据此组织章节与条目顺序。
2. 字段表只是起点，不是终点：在使用字段表骨架时，你必须完整阅读所有其他源文件，**凡是字段表未覆盖的内容维度（新的信息类别、额外的章节主题），必须在骨架中为其扩建相应章节**，确保所有源文件内容都能找到合适归属，不得因"字段表里没有这一项"而遗漏。
3. 该主骨架里常出现"详见附件""详情见附件""见××附件"等占位指针。你必须**把这些指针替换成对应兄弟源文件里的真实内容**并就地回填。判断方法：看该字段主题（如术语表、FAQ、产品优势、参数表等），到其它源文件中找主题匹配的完整内容填入。回填后，若确实还有无法在任何源文件中找到内容的指针，才保留"详见附件"原样。
4. 没有字段表型文件时，再按信息维度自建骨架。章节维度应由资料实际内容归纳得出。

## 三、去重：只去"逐字重复"，存疑即保留
1. 仅当多处是"明显重复的同一语句或同一事实声明"时才去重；措辞略有差异但可能影响理解、归属或口径的，一律保留。
2. 典型示例：若两段大体重复、仅其中一段结尾多出一项内容，必须保留信息更全的一版（或并列保留差异点），不得当作完全重复而把多出的信息删掉。

## 四、已确认裁定与自动消解的落地（本阶段不再标记冲突）
本文档是冲突裁定完成后的最终稿，所有差异都必须"落地成正文"，不得再以任何形式提示读者"存在冲突/待确认"：
1. **历史已确认决策**（history_resolutions）与**本轮新增决策**（current_resolutions）都属于已确认硬冲突裁定：按每条裁定选中的口径/内容如实写入正文，未被选中的候选口径必须删除，不得保留、不得并列、不得改写、不得推翻或重新引入冲突。
2. **已自动消解差异**（auto_merged）：必须严格按其 resolution 执行——format 采用归一化后的统一写法；mergeable 并列如实保留（或取并集）；authority 采用 resolution 指定的高权威来源口径。它们已不是待确认冲突，不能重新作为冲突写回，也不能忽略其既定处理方式。
3. **清理残留标记**：若源文件中残留 `[冲突标记]`、"该信息当前存在冲突，需人工确认"一类提示、或【整合说明】blockquote，只要对应差异已在上述裁定或 auto_merged 中给出处理方式，必须按结果落地为正文并删除该标记。**最终正文中不得残留任何 [冲突标记]、待确认提示或【整合说明】。**
4. 如果 `history_resolutions` 和 `current_resolutions` 都为空，表示本次扫描没有需要人工裁决的硬冲突；此时你仍需严格执行 auto_merged，并直接生成最终完整正文。

## 五、输出要求
1. 只输出最终《品牌AI知识库.md》Markdown 正文，不要输出 JSON、解释或代码块围栏外的额外说明。
2. 结构用"一、二、三…"配"1.1 / 1.2"层级；完整、无残留未回填的占位符、无摘要式压缩。
3. 输出前自检：源文件里的整段原文（尤其问答每一条、术语每一条、各类描述每一段）是否都已原样进入正文；"详见附件"指针是否已尽量回填；空字段是否标注为（空）；所有已裁决/已消解差异是否已落地且正文无任何 [冲突标记] 或【整合说明】残留；未引入任何源文件中不存在的新事实；重要清单或表格项无遗漏。

历史已确认决策：
{json.dumps(history_resolutions, ensure_ascii=False)}

本轮新增决策：
{json.dumps(current_resolutions, ensure_ascii=False)}

扫描阶段已自动消解的差异（已确认处理方式，生成正文时必须执行）：
{json.dumps(auto_merged or [], ensure_ascii=False)}

源 markdown 文件：
{chr(10).join(source_blocks)}

请直接输出最终完整 Markdown 正文。
""".strip()
    final_markdown = await asyncio.to_thread(call_anthropic_text, prompt, settings=resolved_settings)
    normalized_markdown = str(final_markdown or "").strip()
    if not normalized_markdown:
        raise ValueError("Claude 未返回有效的全量品牌知识库 Markdown")
    return {
        "status": "completed",
        "conflicts": [],
        "conflict_markdown": "",
        "final_markdown": normalized_markdown,
    }


async def generate_brand_ai_knowledge_from_structured_update(
    *,
    brand_name: str,
    previous_ai_knowledge_markdown: str = "",
    structured_knowledge_markdown: str = "",
    knowledge_revision: str = "",
    update_reason: str = "structured_update",
    settings: Settings | None = None,
) -> dict[str, Any]:
    resolved_settings = require_settings(settings)
    normalized_structured_markdown = str(structured_knowledge_markdown or "").strip()
    previous_markdown_block = str(previous_ai_knowledge_markdown or "").strip()
    if not normalized_structured_markdown:
        raise ValueError("structured_knowledge_markdown 不能为空")

    prompt = f"""
你是一名品牌 AI 知识库更新助手。请基于“上一版全量品牌 AI 知识库基线”和“本次更新涉及的结构化变更内容”，生成新版完整《品牌AI知识库》Markdown 正文。

这个任务适用于结构化字段更新：把本次修改、新增或确认后的结构化品牌字段融入上一版全量知识库。

品牌名称：
{brand_name}

更新规则：
1. “上一版全量品牌 AI 知识库基线”是历史完整版本，必须作为新版知识库的主体基线，不要丢弃其中仍然有效、且未被本次更新覆盖的内容。
2. “本次更新涉及的结构化变更内容”只包含本次修改、新增或确认的 section，优先级最高；未出现在其中的 section 不代表删除或清空，应继续沿用上一版基线。
3. 这是一次非删除结构化更新：允许新增、替换、补充本次结构化变更明确覆盖到的内容；未覆盖的内容一律保留，不得主动删除任何旧内容。
4. 生成方式不是重写一份全新文档，而是在上一版全量基线之上，把本次更新明确新增、修改、确认的内容融入进去，形成新版完整 Markdown。
5. 如果本次结构化变更内容与上一版基线冲突，采用本次结构化变更内容；如果本次结构化变更内容没有覆盖某个事项，保留上一版基线中的有效内容。
6. 如果本次结构化变更内容未列出某个字段或 section，不要据此删除上一版中同主题的有效内容；只有本次结构化变更内容明确给出新内容、清空意图或替换口径时，才覆盖旧内容。
7. 不得扫描或假设 OSS converted 目录下的其他文件；只能使用本 prompt 中提供的两类输入。
8. 不得编造两类输入中都没有的新事实。
9. 输出必须是完整 Markdown 正文，不要输出 JSON、解释文字或代码块围栏。
10. 文档要结构清晰，适合作为品牌 AI 知识库下载文件。

上一版全量品牌 AI 知识库基线：
```markdown
{previous_markdown_block or "无"}
```

本次更新涉及的结构化变更内容：
```markdown
{normalized_structured_markdown or "未提供"}
```

请直接输出新版完整 Markdown 正文。
""".strip()

    final_markdown = await asyncio.to_thread(call_anthropic_text, prompt, settings=resolved_settings)
    normalized_markdown = str(final_markdown or "").strip()
    if not normalized_markdown:
        raise ValueError("Claude 未返回有效的品牌 AI 知识库 Markdown")
    return {
        "status": "completed",
        "conflicts": [],
        "conflict_markdown": "",
        "final_markdown": normalized_markdown,
    }


async def generate_brand_ai_knowledge_from_merged_sources(
    *,
    brand_name: str,
    previous_ai_knowledge_markdown: str = "",
    structured_knowledge_markdown: str = "",
    knowledge_revision: str = "",
    deleted_sections: list[str] | None = None,
    update_reason: str = "brand_full_knowledge_refresh",
    settings: Settings | None = None,
) -> dict[str, Any]:
    resolved_settings = require_settings(settings)
    normalized_structured_markdown = str(structured_knowledge_markdown or "").strip()
    previous_markdown_block = str(previous_ai_knowledge_markdown or "").strip()
    if not normalized_structured_markdown:
        raise ValueError("structured_knowledge_markdown 不能为空")

    deleted_sections_prompt = json.dumps(deleted_sections or [], ensure_ascii=False)
    prompt = f"""
你是一名品牌 AI 知识库合并更新助手。请基于“上一版全量品牌 AI 知识库基线”和“本轮合并变更来源”，生成新版完整《品牌AI知识库》Markdown 正文。

这个任务适用于品牌级合并刷新：本轮输入可能同时包含 knowledge_update 结构化字段变更、attachment_confirm 附件确认稿，以及删除/收缩类变更。

品牌名称：
{brand_name}

本轮明确删除或收缩的结构化 section：
{deleted_sections_prompt}

合并更新规则：
1. “上一版全量品牌 AI 知识库基线”是历史完整版本，必须作为新版知识库的主体基线；未被本轮变更覆盖的内容默认沿用上一版。
2. “本轮合并变更来源”是本轮所有未消费 audit 的汇总，可能包含多个 source_type。所有来源都要纳入同一次更新判断，不要只处理其中一类。
3. 对 `source_type = knowledge_update`：以每个 section 的“本次更新后的内容”为准；“变更前内容”只用于理解差异，不应把旧内容重新带回。
4. 对 `source_type = attachment_confirm`：附件确认 Markdown 是已经确认后的最终资料，应作为新增、补充或覆盖依据；如果它和旧基线冲突，以附件确认稿为准。
5. 对“本轮明确删除或收缩的结构化 section”：从上一版中移除本轮已经明确删除的旧内容；如果该 section 的本次更新后内容仍保留部分条目，只删除被移除的部分，不要清空整个 section。
6. 对未出现在删除/收缩列表中的 section：按普通更新处理。若本轮提供新内容，则融合或覆盖旧内容；若本轮没有覆盖，继续保留上一版有效内容。
7. 不得扫描或假设 OSS converted 目录下的其他文件；只能使用本 prompt 中提供的两类输入。
8. 不得编造两类输入中都没有的新事实，也不得借由改写、扩写、并列表述的方式恢复已删除内容。
9. 输出必须是完整 Markdown 正文，不要输出 JSON、解释文字或代码块围栏。
10. 文档要结构清晰，适合作为品牌 AI 知识库下载文件。

上一版全量品牌 AI 知识库基线：
```markdown
{previous_markdown_block or "无"}
```

本轮合并变更来源：
```markdown
{normalized_structured_markdown or "未提供"}
```

请直接输出新版完整 Markdown 正文。
""".strip()

    final_markdown = await asyncio.to_thread(call_anthropic_text, prompt, settings=resolved_settings)
    normalized_markdown = str(final_markdown or "").strip()
    if not normalized_markdown:
        raise ValueError("Claude 未返回有效的合并来源品牌 AI 知识库 Markdown")
    return {
        "status": "completed",
        "conflicts": [],
        "conflict_markdown": "",
        "final_markdown": normalized_markdown,
    }


async def generate_brand_ai_knowledge_from_structured_change(
    *,
    brand_name: str,
    previous_ai_knowledge_markdown: str = "",
    structured_knowledge_markdown: str = "",
    knowledge_revision: str = "",
    deleted_sections: list[str] | None = None,
    update_reason: str = "structured_change",
    settings: Settings | None = None,
) -> dict[str, Any]:
    resolved_settings = require_settings(settings)
    normalized_structured_markdown = str(structured_knowledge_markdown or "").strip()
    previous_markdown_block = str(previous_ai_knowledge_markdown or "").strip()
    if not normalized_structured_markdown:
        raise ValueError("structured_knowledge_markdown 不能为空")

    deleted_sections_prompt = json.dumps(deleted_sections or [], ensure_ascii=False)
    prompt = f"""
你是一名品牌 AI 知识库更新助手。请基于“上一版全量品牌 AI 知识库基线”和“本次更新涉及的结构化变更内容”，生成新版完整《品牌AI知识库》Markdown 正文。

这个任务适用于“修改 + 删除/收缩”并存的混合更新：既要把本次新增、修改、确认后的结构化内容写入新版知识库，也要把本次明确删除或收缩的旧内容从上一版中移除。

品牌名称：
{brand_name}

本次明确删除或收缩的结构化 section：
{deleted_sections_prompt}

混合更新规则：
1. “上一版全量品牌 AI 知识库基线”是历史完整版本，必须作为新版知识库的主体基线；未被本次更新覆盖的内容默认沿用上一版。
2. “本次更新涉及的结构化变更内容”包含本次新增、修改、确认以及删除/收缩后的最新结构化事实，是本次更新的最高优先级依据。
3. 对未出现在“本次明确删除或收缩的结构化 section”中的 section：按普通更新处理。若本次结构化内容提供了新值，则用新值覆盖旧值；若未覆盖，则保留上一版有效内容。
4. 对出现在“本次明确删除或收缩的结构化 section”中的 section：既要删除上一版里已经被移除的旧内容，也要保留本次结构化内容里仍然存在的条目；不得把已删除内容从上一版中带回。
5. 如果某个删除/收缩 section 在本次结构化内容中已经为空，则删除上一版中该 section 对应的旧条目、旧小节或旧表述；删除后若该小节已无有效内容，可一并移除空标题或空表格。
6. 这是一次“增量融合 + 定点删除”的混合更新，不是整篇重写；不要为了统一风格而改写未受影响内容的措辞、结构和排版。
7. 不得扫描或假设 OSS converted 目录下的其他文件；只能使用本 prompt 中提供的两类输入。
8. 不得编造两类输入中都没有的新事实，也不得借由补写、改写或并列表述的方式变相恢复已删除内容。
9. 输出必须是完整 Markdown 正文，不要输出 JSON、解释文字或代码块围栏。
10. 最终产物应同时满足两点：本次修改内容已经生效，本次删除/收缩内容也已从上一版中移除。

上一版全量品牌 AI 知识库基线：
```markdown
{previous_markdown_block or "无"}
```

本次更新涉及的结构化变更内容：
```markdown
{normalized_structured_markdown or "未提供"}
```

请直接输出新版完整 Markdown 正文。
""".strip()

    final_markdown = await asyncio.to_thread(call_anthropic_text, prompt, settings=resolved_settings)
    normalized_markdown = str(final_markdown or "").strip()
    if not normalized_markdown:
        raise ValueError("Claude 未返回有效的混合更新品牌 AI 知识库 Markdown")
    return {
        "status": "completed",
        "conflicts": [],
        "conflict_markdown": "",
        "final_markdown": normalized_markdown,
    }


async def generate_brand_ai_knowledge_from_structured_deletion(
    *,
    brand_name: str,
    previous_ai_knowledge_markdown: str = "",
    structured_knowledge_markdown: str = "",
    knowledge_revision: str = "",
    deleted_sections: list[str] | None = None,
    update_reason: str = "structured_delete",
    settings: Settings | None = None,
) -> dict[str, Any]:
    resolved_settings = require_settings(settings)
    normalized_structured_markdown = str(structured_knowledge_markdown or "").strip()
    previous_markdown_block = str(previous_ai_knowledge_markdown or "").strip()
    if not normalized_structured_markdown:
        raise ValueError("structured_knowledge_markdown 不能为空")

    deleted_sections_prompt = json.dumps(deleted_sections or [], ensure_ascii=False)
    prompt = f"""
你是一名品牌 AI 知识库删除更新助手。你的唯一任务是：在“上一版全量品牌 AI 知识库基线”的基础上，把本次被删除/收缩的内容剔除掉，其余一切原样保留。这是一次“定点删除”，不是重新生成、不是重写、不是重新组织。

核心原则（最重要）：
- 以“上一版全量品牌 AI 知识库基线”为最终产物的骨架和唯一底本，逐字保留其标题层级、章节顺序、小节结构、表格、列表、措辞和排版格式。
- 只做“减法”：仅移除本次删除/收缩涉及的具体内容，绝不改写、重排、合并、扩写或重新总结任何未受影响的文字。
- 未被删除的内容必须与上一版基线保持逐字一致（除了因删除而需要连带清理的空标题/空表格行等收尾工作）。

品牌名称：
{brand_name}

本次明确存在删除/收缩的结构化 section：
{deleted_sections_prompt}

删除更新规则：
1. 逐字保留上一版基线的整体结构（标题、顺序、层级、表格、列表、排版），默认对每一段内容都原样搬运。
2. 只针对“本次明确存在删除/收缩的结构化 section”所对应的内容做删除处理，其它 section 一律不改动。
3. 如果某个删除 section 在“本次更新涉及的结构化删除/收缩内容”中已为空，则删除上一版中该 section 对应的旧条目、旧小节或旧表述；若删除后该小节/标题下已无任何有效内容，可一并移除该空标题或空表格，避免留下空壳。
4. 如果某个删除 section 在本次内容中仍保留部分条目，则只删除上一版中那些已不再存在的条目，保留仍然存在的条目及其原有措辞与格式，不要改写留下来的条目。
5. 对未出现在删除列表中的 section，一律原样保留上一版内容，不得以任何理由改动。
6. 不得把已删除内容从上一版中带回，也不得借由补写、改写或并列表述的方式变相恢复。
7. 不得扫描或假设 OSS converted 目录下的其他文件；只能使用本 prompt 中提供的两类输入。
8. 不得新增任何上一版基线中没有的事实、章节或措辞。
9. 输出必须是完整 Markdown 正文，不要输出 JSON、解释文字或代码块围栏，也不要输出任何“已删除xxx”之类的变更说明。
10. 最终产物应当读起来就像“上一版基线删掉了几处内容”，整体结构、风格、格式与上一版保持一致。

上一版全量品牌 AI 知识库基线：
```markdown
{previous_markdown_block or "无"}
```

本次更新涉及的结构化删除/收缩内容：
```markdown
{normalized_structured_markdown or "未提供"}
```

请直接输出新版完整 Markdown 正文。
""".strip()

    final_markdown = await asyncio.to_thread(call_anthropic_text, prompt, settings=resolved_settings)
    normalized_markdown = str(final_markdown or "").strip()
    if not normalized_markdown:
        raise ValueError("Claude 未返回有效的删除后品牌 AI 知识库 Markdown")
    return {
        "status": "completed",
        "conflicts": [],
        "conflict_markdown": "",
        "final_markdown": normalized_markdown,
    }

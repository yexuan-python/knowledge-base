import { useState } from "react";

import SectionIntro from "../../components/SectionIntro";
import { searchBrandFacts, searchDocuments } from "../../api/knowledgeBaseApi";
import type { ActivityItem, BrandFactsResponse, SearchResponse } from "../../types";

export type SearchWorkspaceProps = {
  onActivity: (title: string, detail: string, tone?: ActivityItem["tone"]) => void;
};

export default function SearchWorkspace(props: SearchWorkspaceProps) {
  const { onActivity } = props;
  const [query, setQuery] = useState("");
  const [topK, setTopK] = useState("5");
  const [brandName, setBrandName] = useState("");
  const [documentIds, setDocumentIds] = useState("");
  const [sourceTypes, setSourceTypes] = useState("");
  const [subcategory, setSubcategory] = useState("");
  const [searchResult, setSearchResult] = useState<SearchResponse | null>(null);
  const [factsBrandName, setFactsBrandName] = useState("");
  const [brandFactsQuery, setBrandFactsQuery] = useState("");
  const [brandFactsResult, setBrandFactsResult] = useState<BrandFactsResponse | null>(null);
  const [loadingAction, setLoadingAction] = useState<string | null>(null);

  async function handleSearch() {
    if (!query.trim()) {
      return;
    }
    setLoadingAction("search");
    try {
      const response = await searchDocuments({
        query: query.trim(),
        topK: Number(topK) || 5,
        brandName: brandName.trim() || undefined,
        subcategory: subcategory.trim() || undefined,
        documentIds: documentIds
          .split(",")
          .map((item) => item.trim())
          .filter(Boolean),
        sourceTypes: sourceTypes
          .split(",")
          .map((item) => item.trim())
          .filter(Boolean),
      });
      setSearchResult(response);
      onActivity("语义搜索完成", `${query.trim()} · ${response.data.length} 条`, "success");
    } catch (error) {
      onActivity("语义搜索失败", error instanceof Error ? error.message : "未知错误", "warning");
    } finally {
      setLoadingAction(null);
    }
  }

  async function handleBrandFactsSearch() {
    if (!factsBrandName.trim()) {
      return;
    }
    setLoadingAction("brand-facts");
    try {
      const response = await searchBrandFacts({
        brandName: factsBrandName.trim(),
        query: brandFactsQuery.trim() || undefined,
        topK: Number(topK) || 5,
      });
      setBrandFactsResult(response);
      onActivity("品牌 facts 查询完成", `${response.brand_name || response.category || "-"} · ${response.facts.length} 条`, "success");
    } catch (error) {
      onActivity("品牌 facts 查询失败", error instanceof Error ? error.message : "未知错误", "warning");
    } finally {
      setLoadingAction(null);
    }
  }

  return (
    <div className="workspace-grid">
      <section className="surface-panel">
        <SectionIntro
          eyebrow="Semantic Search"
          title="检索调试台"
          description="快速验证正式知识库是否可搜、品牌 facts 是否命中，以及 latest 正式知识库过滤是否符合预期。"
        />
        <div className="card-grid two-columns">
          <div className="detail-card">
            <div className="detail-card-title">通用搜索</div>
            <label className="field-block">
              <span>query</span>
              <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="品牌手册讲了什么" />
            </label>
            <div className="two-up-row">
              <label className="field-block">
                <span>top_k</span>
                <input value={topK} onChange={(event) => setTopK(event.target.value)} />
              </label>
              <label className="field-block">
                <span>brand_name</span>
                <input value={brandName} onChange={(event) => setBrandName(event.target.value)} />
              </label>
            </div>
            <label className="field-block">
              <span>subcategory</span>
              <input value={subcategory} onChange={(event) => setSubcategory(event.target.value)} />
            </label>
            <label className="field-block">
              <span>document_ids（逗号分隔）</span>
              <input value={documentIds} onChange={(event) => setDocumentIds(event.target.value)} />
            </label>
            <label className="field-block">
              <span>source_types（逗号分隔）</span>
              <input
                value={sourceTypes}
                onChange={(event) => setSourceTypes(event.target.value)}
                placeholder="pdf,docx,image"
              />
            </label>
            <button type="button" onClick={() => void handleSearch()} disabled={loadingAction === "search"}>
              {loadingAction === "search" ? "检索中..." : "执行语义搜索"}
            </button>
            <pre className="code-block">
              {searchResult ? JSON.stringify(searchResult, null, 2) : "搜索结果会展示在这里。"}
            </pre>
          </div>

          <div className="detail-card">
            <div className="detail-card-title">品牌 Facts 搜索</div>
            <label className="field-block">
              <span>brand_name</span>
              <input value={factsBrandName} onChange={(event) => setFactsBrandName(event.target.value)} />
            </label>
            <label className="field-block">
              <span>query（可选）</span>
              <input value={brandFactsQuery} onChange={(event) => setBrandFactsQuery(event.target.value)} />
            </label>
            <button
              type="button"
              className="secondary-button"
              onClick={() => void handleBrandFactsSearch()}
              disabled={loadingAction === "brand-facts"}
            >
              {loadingAction === "brand-facts" ? "查询中..." : "执行品牌 facts 搜索"}
            </button>
            <pre className="code-block">
              {brandFactsResult
                ? JSON.stringify(brandFactsResult, null, 2)
                : "品牌 facts 结果会展示在这里。"}
            </pre>
          </div>
        </div>
      </section>
    </div>
  );
}

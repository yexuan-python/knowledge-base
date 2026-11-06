import SectionIntro from "../components/SectionIntro";
import type { DashboardMetrics, UploadTaskFileStatus } from "../types";

function renderFileSecondaryStatus(file: UploadTaskFileStatus): string {
  const statusParts = [
    file.current_step,
    file.ingest_status,
    file.milvus_status,
    file.facts_status,
  ].filter(Boolean);
  return statusParts.join(" / ");
}

type DashboardPageProps = {
  metrics: DashboardMetrics;
  onRefreshHealth: () => Promise<void>;
};

export default function DashboardPage(props: DashboardPageProps) {
  const { metrics } = props;

  return (
    <div className="workspace-grid">
      <section className="surface-panel">
        <SectionIntro
          eyebrow="Overview"
          title="系统概览"
          description="把当前 API 状态、任务运行和最近动作聚合到一个面板里。"
        />
        <div className="stats-grid">
          <div className="stat-card">
            <div className="stat-label">API 基地址</div>
            <div className="stat-value selectable-text">{metrics.apiBaseUrl || "同源 /api 代理"}</div>
          </div>
          <div className="stat-card">
            <div className="stat-label">健康状态</div>
            <div className="stat-value">{metrics.health ? metrics.health.status : "未检测"}</div>
            <div className="stat-footnote">Collection：{metrics.health?.collection_name || "-"}</div>
          </div>
          <div className="stat-card">
            <div className="stat-label">最近任务</div>
            <div className="stat-value">{metrics.lastTask ? metrics.lastTask.status : "暂无"}</div>
            <div className="stat-footnote">
              {metrics.lastTask ? metrics.lastTask.task_id : "还没有触发过上传任务"}
            </div>
          </div>
          <div className="stat-card">
            <div className="stat-label">最近知识会话</div>
            <div className="stat-value">{metrics.lastSession ? metrics.lastSession.status : "暂无"}</div>
            <div className="stat-footnote">
              {metrics.lastSession
                ? `${metrics.lastSession.brand_name} · 第 ${metrics.lastSession.round_no} 轮`
                : "尚未创建会话"}
            </div>
          </div>
        </div>
        <div className="inline-actions">
          <button type="button" className="secondary-button" onClick={() => void props.onRefreshHealth()}>
            重新检查健康状态
          </button>
        </div>

        {metrics.lastTask ? (
          <div className="result-panel" style={{ marginTop: 16 }}>
            <div className="result-line">
              <strong>任务类型：</strong>
              {metrics.lastTask.task_type || "-"}
            </div>
            <div className="result-line">
              <strong>品牌：</strong>
              {metrics.lastTask.brand_name || "-"}
              {metrics.lastTask.brand_code ? ` · ${metrics.lastTask.brand_code}` : ""}
            </div>
            <div className="result-line">
              <strong>文件进度：</strong>
              {metrics.lastTask.success_count}/{metrics.lastTask.file_count} 成功 · {metrics.lastTask.failed_count} 失败 · {metrics.lastTask.processing_count} 处理中
            </div>
            {metrics.lastTask.files.length ? (
              <div className="activity-list" style={{ marginTop: 12 }}>
                {metrics.lastTask.files.map((file) => (
                  <div key={`${file.file_id}-${file.file_index}`} className="activity-item activity-neutral">
                    <div className="activity-head">
                      <strong>{file.file_name}</strong>
                      <span>{file.status}</span>
                    </div>
                    <div className="activity-detail">
                      {[file.file_role, file.source_type, renderFileSecondaryStatus(file)].filter(Boolean).join(" · ") || "等待更多状态"}
                    </div>
                    {file.error_message ? (
                      <div className="activity-detail" style={{ marginTop: 4 }}>
                        {file.error_message}
                      </div>
                    ) : null}
                  </div>
                ))}
              </div>
            ) : null}
          </div>
        ) : null}
      </section>

      <section className="surface-panel">
        <SectionIntro
          eyebrow="Activity"
          title="最近操作"
          description="保留最近一次上传、删除、检索、会话等关键动作，方便快速回看。"
        />
        <div className="activity-list">
          {metrics.recentActivities.length ? (
            metrics.recentActivities.map((activity) => (
              <div key={activity.id} className={`activity-item activity-${activity.tone}`}>
                <div className="activity-head">
                  <strong>{activity.title}</strong>
                  <span>{activity.createdAt}</span>
                </div>
                <div className="activity-detail">{activity.detail}</div>
              </div>
            ))
          ) : (
            <div className="empty-state">还没有记录操作，先试试创建品牌、读取文件或发起知识会话。</div>
          )}
        </div>
      </section>
    </div>
  );
}

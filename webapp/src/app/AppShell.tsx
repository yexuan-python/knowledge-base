import type { ReactNode } from "react";

import { NAV_ITEMS } from "./navigation";
import type { NavigationKey } from "../types";

type AppShellProps = {
  activeNav: NavigationKey;
  apiBaseLabel: string;
  healthStatus?: string | null;
  selectedBrandName?: string;
  onNavChange: (key: NavigationKey) => void;
  children: ReactNode;
};

export default function AppShell(props: AppShellProps) {
  const {
    activeNav,
    apiBaseLabel,
    healthStatus,
    selectedBrandName,
    onNavChange,
    children,
  } = props;

  return (
    <div className="admin-shell">
      <aside className="admin-sidebar">
        <div className="brand-badge">Knowledge Base Console</div>
        <div className="sidebar-title">知识库管理台</div>
        <div className="sidebar-subtitle">把品牌、文档、检索和知识编排都收在一个操作台里。</div>

        <nav className="nav-list">
          {NAV_ITEMS.map((item) => (
            <button
              key={item.key}
              type="button"
              className={`nav-item ${activeNav === item.key ? "nav-item-active" : ""}`}
              onClick={() => onNavChange(item.key)}
            >
              <span className="nav-item-label">{item.label}</span>
              <span className="nav-item-description">{item.description}</span>
            </button>
          ))}
        </nav>
      </aside>

      <main className="admin-main">
        <header className="topbar">
          <div>
            <div className="eyebrow">Control Room</div>
            <h1>知识库项目管理后台</h1>
          </div>
          <div className="topbar-status">
            <span className="status-pill">API：{apiBaseLabel}</span>
            <span className="status-pill">健康：{healthStatus || "未检测"}</span>
            {selectedBrandName ? <span className="status-pill">当前品牌：{selectedBrandName}</span> : null}
          </div>
        </header>

        <section className="content-stage">{children}</section>
      </main>
    </div>
  );
}

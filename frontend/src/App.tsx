import { useEffect, useMemo, useState } from "react";
import "./App.css";

import { ArtifactPanel } from "./components/artifacts/ArtifactPanel";
import { AskUserCard } from "./components/chat/AskUserCard";
import { ChatPanel } from "./components/chat/ChatPanel";
import { DatabaseMapPanel } from "./components/database/DatabaseMapPanel";
import { PipelinePanel } from "./components/pipeline/PipelinePanel";
import { ActivityTicker } from "./components/status/ActivityTicker";
import { ConnectionBadge } from "./components/status/ConnectionBadge";
import { ErrorPanel } from "./components/status/ErrorPanel";
import { TraceTreePanel } from "./components/trace/TraceTreePanel";
import { useRunController } from "./hooks/useRunController";
import type { AnswerSubmission, RunState, RunStatus } from "./types/run";

type TopLevelPage = "overview" | "workflow" | "database" | "pipeline";
type WorkspaceTab = "overview" | "request" | "decision" | "trace" | "artifacts" | "logs";

type WorkspaceTabConfig = {
  id: WorkspaceTab;
  label: string;
  hint: string;
  badge?: string | number;
};

function formatStatus(status: RunStatus) {
  if (status === "waiting_for_user") return "Waiting for decision";
  return status.charAt(0).toUpperCase() + status.slice(1);
}

function getRecommendedTab(status: RunStatus, artifactCount: number): WorkspaceTab {
  if (status === "waiting_for_user") return "decision";
  if (status === "running") return "trace";
  if (status === "completed" && artifactCount > 0) return "artifacts";
  if (status === "failed") return "logs";
  return "request";
}

function getPrimaryActionLabel(status: RunStatus) {
  if (status === "idle") return "Open Workflow";
  if (status === "waiting_for_user") return "Resolve decision";
  if (status === "completed") return "Review artifacts";
  if (status === "failed") return "Open logs";
  return "Watch trace";
}

function getPrimaryActionTab(status: RunStatus): WorkspaceTab {
  if (status === "waiting_for_user") return "decision";
  if (status === "completed") return "artifacts";
  if (status === "failed") return "logs";
  if (status === "running") return "trace";
  return "request";
}

function getAgentCount(state: RunState) {
  return Object.keys(state.nodes).length;
}

function getToolCount(state: RunState) {
  return Object.values(state.nodes).reduce((count, node) => count + node.tools.length, 0);
}

function getDecisionCount(state: RunState) {
  return state.chatMessages.filter((message) => message.text.startsWith("Answer received:")).length;
}

function getCompletedAgentCount(state: RunState) {
  return Object.values(state.nodes).filter((node) => node.status === "completed").length;
}

function getLatestArtifactNames(state: RunState) {
  return state.artifacts.slice(-5).map((artifact) => artifact.filename);
}

function WorkspaceOverview({
  state,
  onSelectTab
}: {
  state: RunState;
  onSelectTab: (tab: WorkspaceTab) => void;
}) {
  const latestArtifacts = getLatestArtifactNames(state);
  const completedAgents = getCompletedAgentCount(state);
  const agentCount = getAgentCount(state);
  const decisionCount = getDecisionCount(state);
  const latestActivity = state.activity[0] ?? "No run activity yet.";

  return (
    <section className="workspace-overview">
      <div className="overview-hero-card">
        <span className="section-kicker">Run overview</span>
        <h2>{state.status === "idle" ? "Ready to build a data product." : latestActivity}</h2>
        <p>
          PipeForge follows a guided workflow: capture the request, inspect the
          selected data source, ask for business-critical decisions, then produce
          reviewable dbt-style artifacts.
        </p>

        <div className="overview-actions">
          <button type="button" onClick={() => onSelectTab(getPrimaryActionTab(state.status))}>
            {getPrimaryActionLabel(state.status)}
          </button>
          <button type="button" className="ghost-action" onClick={() => onSelectTab("trace")}>
            View execution
          </button>
        </div>
      </div>

      <div className="overview-grid">
        <article className="overview-card">
          <span>Status</span>
          <strong>{formatStatus(state.status)}</strong>
          <p>Current run state and next action.</p>
        </article>

        <article className="overview-card">
          <span>Agents</span>
          <strong>
            {completedAgents}/{agentCount}
          </strong>
          <p>Completed agents across the workflow.</p>
        </article>

        <article className="overview-card">
          <span>Decisions</span>
          <strong>{state.pendingQuestion ? "1 pending" : decisionCount}</strong>
          <p>Business rules resolved by the user.</p>
        </article>

        <article className="overview-card">
          <span>Artifacts</span>
          <strong>{state.artifacts.length}</strong>
          <p>Generated SQL, YAML, tests, and docs.</p>
        </article>
      </div>

      <div className="overview-split">
        <article className="overview-list-card">
          <div className="mini-header">
            <span className="section-kicker">Recent activity</span>
            <button type="button" onClick={() => onSelectTab("logs")}>
              Open logs
            </button>
          </div>

          {state.activity.length === 0 ? (
            <p className="muted-copy">Run events will appear here after you start PipeForge.</p>
          ) : (
            <ol className="mini-timeline">
              {state.activity.slice(0, 6).map((item, index) => (
                <li key={`${item}_${index}`}>{item}</li>
              ))}
            </ol>
          )}
        </article>

        <article className="overview-list-card">
          <div className="mini-header">
            <span className="section-kicker">Latest artifacts</span>
            <button type="button" onClick={() => onSelectTab("artifacts")}>
              Open files
            </button>
          </div>

          {latestArtifacts.length === 0 ? (
            <p className="muted-copy">Generated files will be collected in the Artifacts workspace.</p>
          ) : (
            <ul className="artifact-name-list">
              {latestArtifacts.map((name) => (
                <li key={name}>{name}</li>
              ))}
            </ul>
          )}
        </article>
      </div>
    </section>
  );
}

function DecisionView({
  state,
  onSubmitAnswer
}: {
  state: RunState;
  onSubmitAnswer: (submission: AnswerSubmission) => void;
}) {
  if (!state.pendingQuestion) {
    return (
      <section className="decision-empty-view">
        <div className="empty-state cinematic-empty">
          <div className="empty-icon">✓</div>
          <strong>No decision is waiting right now</strong>
          <p>
            When the agent detects a business-critical data quality question, it
            will appear here with recommended options and a custom rule box.
          </p>
        </div>
      </section>
    );
  }

  return (
    <section className="decision-workspace">
      <div className="decision-copy">
        <span className="section-kicker">Human approval gate</span>
        <h2>Resolve this business rule before generation continues.</h2>
        <p>
          This mirrors workflow tools where data pipeline runs pause for review
          before downstream assets are generated.
        </p>
      </div>

      <AskUserCard question={state.pendingQuestion} onSubmit={onSubmitAnswer} />
    </section>
  );
}

function ResetRunDialog({
  onCancel,
  onConfirm
}: {
  onCancel: () => void;
  onConfirm: () => void;
}) {
  return (
    <div
      className="reset-dialog-overlay"
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) {
          onCancel();
        }
      }}
    >
      <section
        className="reset-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="reset-dialog-title"
        aria-describedby="reset-dialog-description"
      >
        <div className="reset-dialog-icon">↻</div>

        <div className="reset-dialog-copy">
          <span className="section-kicker">Start fresh</span>
          <h2 id="reset-dialog-title">Start a new run?</h2>
          <p id="reset-dialog-description">
            This will clear the current workspace in the UI so you can begin again
            without refreshing the browser.
          </p>

          <div className="reset-dialog-note">
            The current backend run may continue in the background. This action only
            resets the frontend workspace.
          </div>
        </div>

        <div className="reset-dialog-actions">
          <button type="button" className="reset-dialog-secondary" onClick={onCancel}>
            Keep current run
          </button>
          <button type="button" className="reset-dialog-primary" onClick={onConfirm}>
            Start new run
          </button>
        </div>
      </section>
    </div>
  );
}

function App() {
  const controller = useRunController();
  const { state } = controller;

  const [activePage, setActivePage] = useState<TopLevelPage>("overview");
  const [activeTab, setActiveTab] = useState<WorkspaceTab>("request");
  const [manualPageSelected, setManualPageSelected] = useState(false);
  const [manualTabSelected, setManualTabSelected] = useState(false);
  const [showResetDialog, setShowResetDialog] = useState(false);

  const agentCount = getAgentCount(state);
  const toolCount = getToolCount(state);
  const artifactCount = state.artifacts.length;
  const decisionCount = getDecisionCount(state);
  const latestActivity = state.activity[0] ?? "Ready to build your next data product.";

  const tabs = useMemo<WorkspaceTabConfig[]>(
    () => [
      {
        id: "overview",
        label: "Overview",
        hint: "Run summary"
      },
      {
        id: "request",
        label: "Request",
        hint: "Prompt and chat"
      },
      {
        id: "decision",
        label: "Decision",
        hint: "Business rules",
        badge: state.pendingQuestion ? "Action" : undefined
      },
      {
        id: "trace",
        label: "Trace",
        hint: "Agent workflow",
        badge: agentCount || undefined
      },
      {
        id: "artifacts",
        label: "Artifacts",
        hint: "Generated package",
        badge: artifactCount || undefined
      },
      {
        id: "logs",
        label: "Logs",
        hint: "Activity and errors",
        badge: state.errors.length || state.activity.length || undefined
      }
    ],
    [agentCount, artifactCount, state.activity.length, state.errors.length, state.pendingQuestion]
  );

  useEffect(() => {
    if (!manualTabSelected) {
      setActiveTab(getRecommendedTab(state.status, artifactCount));
    }
  }, [artifactCount, manualTabSelected, state.status]);

  useEffect(() => {
    setManualTabSelected(false);

    if (state.runId) {
      setActivePage("workflow");
      setManualPageSelected(false);
    } else {
      setActivePage("overview");
      setManualPageSelected(false);
    }
  }, [state.runId]);

  useEffect(() => {
    if (!manualPageSelected && state.status !== "idle") {
      setActivePage("workflow");
    }
  }, [manualPageSelected, state.status]);

  function openOverview() {
    setActivePage("overview");
    setManualPageSelected(true);
  }

  function openWorkflow(tab?: WorkspaceTab) {
    setActivePage("workflow");
    setManualPageSelected(true);

    if (tab) {
      setActiveTab(tab);
      setManualTabSelected(true);
    }
  }

  function openDatabase() {
    setActivePage("database");
    setManualPageSelected(true);
  }

  function openPipeline() {
    setActivePage("pipeline");
    setManualPageSelected(true);
  }

  function selectTab(tab: WorkspaceTab) {
    setActiveTab(tab);
    setManualTabSelected(true);
  }

  function completeWorkspaceReset() {
    controller.resetRun();
    setActivePage("overview");
    setActiveTab("request");
    setManualPageSelected(false);
    setManualTabSelected(false);
    setShowResetDialog(false);
  }

  function requestWorkspaceReset() {
    const isActiveRun = state.status === "running" || state.status === "waiting_for_user";

    if (isActiveRun) {
      setShowResetDialog(true);
      return;
    }

    completeWorkspaceReset();
  }

  function renderActiveWorkspace() {
    switch (activeTab) {
      case "overview":
        return <WorkspaceOverview state={state} onSelectTab={selectTab} />;

      case "request":
        return (
          <ChatPanel
            messages={state.chatMessages}
            status={state.status}
            pendingQuestion={state.pendingQuestion}
            showPendingQuestion={false}
            onOpenDecision={() => selectTab("decision")}
            onStartRun={controller.startRun}
            onSubmitAnswer={controller.submitAnswer}
          />
        );

      case "decision":
        return <DecisionView state={state} onSubmitAnswer={controller.submitAnswer} />;

      case "trace":
        return <TraceTreePanel state={state} onToggleNode={controller.toggleNode} />;

      case "artifacts":
        return (
            <ArtifactPanel
              artifacts={state.artifacts}
              onOpenPipeline={openPipeline}
            />
          );

      case "logs":
        return (
          <div className="logs-workspace">
            <ActivityTicker activity={state.activity} />
            <ErrorPanel
              errors={state.errors}
              canRetry={state.status === "failed"}
              onRetry={() => controller.retry()}
            />
          </div>
        );

      default:
        return null;
    }
  }

  return (
    <div className={`app-shell app-shell-${activePage}`}>
      <div className="hero-noise" />
      <div className="hero-glow hero-glow-pink" />
      <div className="hero-glow hero-glow-orange" />
      <div className="hero-glow hero-glow-blue" />

      <div className="app-container">
        <nav className="top-nav">
          <button type="button" className="nav-brand nav-brand-button" onClick={openOverview}>
            <div className="brand-mark">PF</div>
            <span>PipeForge</span>
          </button>

          <div className="nav-links" aria-label="Product sections">
            <button
              type="button"
              className={activePage === "overview" ? "active" : ""}
              onClick={openOverview}
            >
              Overview
            </button>
            <button
              type="button"
              className={
                activePage === "workflow" && !["artifacts", "logs"].includes(activeTab)
                  ? "active"
                  : ""
              }
              onClick={() => openWorkflow(getRecommendedTab(state.status, artifactCount))}
            >
              Workflow
            </button>
            <button
              type="button"
              className={activePage === "database" ? "active" : ""}
              onClick={openDatabase}
            >
              Database
            </button>
            <button
              type="button"
              className={activePage === "pipeline" ? "active" : ""}
              onClick={openPipeline}
            >
              Pipeline
            </button>
            <button
              type="button"
              className={activePage === "workflow" && activeTab === "artifacts" ? "active" : ""}
              onClick={() => openWorkflow("artifacts")}
            >
              Artifacts
            </button>
            <button
              type="button"
              className={activePage === "workflow" && activeTab === "logs" ? "active" : ""}
              onClick={() => openWorkflow("logs")}
            >
              Logs
            </button>
          </div>

          <div className="nav-actions">
            {state.status !== "idle" && (
              <button type="button" className="nav-reset-button" onClick={requestWorkspaceReset}>
                New run
              </button>
            )}
            <ConnectionBadge connected={state.connected} />
          </div>
        </nav>

        {activePage === "overview" ? (
          <main className="landing-page">
            <header className="story-hero">
              <div className="story-hero-copy">
                <p className="eyebrow">Transparent AI Data Product Builder</p>
                <h1>Build reviewable data products from business requests.</h1>
                <p>
                  PipeForge profiles data sources, asks business-critical decisions,
                  and generates dbt-style SQL, tests, docs, and business rules in a
                  guided agent workspace.
                </p>

                <div className="hero-command-row">
                  <button
                    type="button"
                    className="hero-primary-action"
                    onClick={() => openWorkflow(getPrimaryActionTab(state.status))}
                  >
                    {getPrimaryActionLabel(state.status)}
                  </button>

                  <button
                    type="button"
                    className="hero-command"
                    onClick={() => openWorkflow("request")}
                  >
                    <span>Prompt</span>
                    <code>monthly revenue from Stripe</code>
                  </button>
                </div>
              </div>

              <aside className="hero-run-card">
                <div className="run-card-top">
                  <span>Live run</span>
                  <strong>{formatStatus(state.status)}</strong>
                </div>
                <p>{latestActivity}</p>
                <div className="run-id-card">
                  <span>Run ID</span>
                  <code>{state.runId ?? "not started"}</code>
                </div>
              </aside>
            </header>

            <section className="hero-stats" aria-label="Run metrics">
              <article>
                <span>Status</span>
                <strong>{formatStatus(state.status)}</strong>
              </article>
              <article>
                <span>Agents</span>
                <strong>{agentCount}</strong>
              </article>
              <article>
                <span>Tools</span>
                <strong>{toolCount}</strong>
              </article>
              <article>
                <span>Decisions</span>
                <strong>{state.pendingQuestion ? "1 pending" : decisionCount}</strong>
              </article>
              <article>
                <span>Artifacts</span>
                <strong>{artifactCount}</strong>
              </article>
            </section>
          </main>
        ) : activePage === "database" ? (
          <main className="database-page">
            <DatabaseMapPanel />
          </main>
        ) : activePage === "pipeline" ? (
          <main className="pipeline-page">
            <PipelinePanel
              runId={state.runId}
              artifacts={state.artifacts}
              onOpenArtifacts={() => openWorkflow("artifacts")}
            />
          </main>
        ) : (
          <main className="workflow-page">
            <section className="product-window">
              <div className="window-chrome">
                <div className="window-dots" aria-hidden="true">
                  <span />
                  <span />
                  <span />
                </div>

                <div className="window-title">
                  <strong>PipeForge Workspace</strong>
                  <span>{latestActivity}</span>
                </div>

                <div className="window-status-strip">
                  {state.status !== "idle" && (
                    <button
                      type="button"
                      className="window-reset-button"
                      onClick={requestWorkspaceReset}
                    >
                      New run
                    </button>
                  )}

                  <div className="window-mini-metric">
                    <strong>{agentCount}</strong>
                    <span>Agents</span>
                  </div>
                  <div className="window-mini-metric">
                    <strong>{toolCount}</strong>
                    <span>Tools</span>
                  </div>
                  <div className="window-mini-metric">
                    <strong>{artifactCount}</strong>
                    <span>Artifacts</span>
                  </div>

                  <button
                    type="button"
                    className="window-run-pill"
                    onClick={() => selectTab(getPrimaryActionTab(state.status))}
                  >
                    {formatStatus(state.status)}
                  </button>
                </div>
              </div>

              <div className="workspace-body">
                <aside className="workspace-sidebar" aria-label="PipeForge workspaces">
                  <div className="sidebar-label">Workspace modes</div>

                  <div className="workspace-tabs" role="tablist" aria-label="PipeForge workspaces">
                    {tabs.map((tab) => (
                      <button
                        key={tab.id}
                        type="button"
                        role="tab"
                        aria-selected={activeTab === tab.id}
                        className={activeTab === tab.id ? "workspace-tab active" : "workspace-tab"}
                        onClick={() => selectTab(tab.id)}
                      >
                        <span>{tab.label}</span>
                        <small>{tab.hint}</small>
                        {tab.badge !== undefined && <em>{tab.badge}</em>}
                      </button>
                    ))}
                  </div>
                </aside>

                <div className="workspace-stage">{renderActiveWorkspace()}</div>
              </div>
            </section>
          </main>
        )}
      </div>

      {showResetDialog && (
        <ResetRunDialog
          onCancel={() => setShowResetDialog(false)}
          onConfirm={completeWorkspaceReset}
        />
      )}
    </div>
  );
}

export default App;
import { useEffect, useMemo, useRef, useState } from "react";
import type { PointerEvent, ReactNode } from "react";

import {
  executePipeline,
  getPipelineStatus,
  getPipelineTablePreview,
  pipelineTableCsvUrl,
  pipelineZipUrl,
} from "../../api/pipelineApi";
import { getArtifactContent } from "../../api/runsApi";
import type { Artifact } from "../../types/artifact";
import type {
  PipelineModelStep,
  PipelineRun,
  PipelineTable,
  PipelineTablePreview,
} from "../../types/pipeline";

type PipelinePanelProps = {
  runId?: string;
  artifacts: Artifact[];
  onOpenArtifacts: () => void;
};

type PositionedPipelineNode = PipelineModelStep & {
  x: number;
  y: number;
  layer: number;
  table?: PipelineTable;
  artifact?: Artifact;
};

type PipelineEdge = {
  id: string;
  from: string;
  to: string;
  label: string;
};

type PipelineDrawerSections = {
  sql: boolean;
  table: boolean;
};

const NODE_WIDTH = 286;
const NODE_HEIGHT = 156;
const LEVEL_GAP = 430;
const ROW_GAP = 190;
const CANVAS_PADDING_X = 120;
const CANVAS_PADDING_Y = 112;
const MIN_CANVAS_WIDTH = 1320;
const MIN_CANVAS_HEIGHT = 720;

const MIN_ZOOM = 0.45;
const MAX_ZOOM = 1.35;
const ZOOM_STEP = 0.1;
const DEFAULT_ZOOM = 0.82;

function clampZoom(value: number) {
  return Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, Number(value.toFixed(2))));
}

function formatStatus(status: PipelineRun["status"]) {
  if (status === "not_ready") return "Not ready";
  if (status === "not_run") return "Ready to run";
  return status.charAt(0).toUpperCase() + status.slice(1);
}

function formatStepStatus(status: PipelineModelStep["status"]) {
  return status.charAt(0).toUpperCase() + status.slice(1);
}

function formatValue(value: unknown) {
  if (value === null || value === undefined) return "NULL";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function getErrorMessage(error: unknown) {
  if (error instanceof Error) return error.message;
  return String(error);
}

function getSqlArtifactCount(artifacts: Artifact[]) {
  return artifacts.filter(
    (artifact) =>
      artifact.type === "sql" &&
      artifact.filename.endsWith(".sql") &&
      !artifact.filename.includes("custom_tests/") &&
      artifact.filename !== "analytics_query.sql",
  ).length;
}

function getModelNameFromFilename(filename: string) {
  return (
    filename
      .split("/")
      .pop()
      ?.replace(/\.sql$/i, "") ?? filename.replace(/\.sql$/i, "")
  );
}

function getFallbackArtifactSqlPreview(artifact?: Artifact) {
  return (
    artifact?.content ??
    artifact?.contentPreview ??
    "No SQL preview is available for this artifact."
  );
}

function findArtifactForModel(model: PipelineModelStep, artifacts: Artifact[]) {
  return (
    artifacts.find((artifact) => artifact.id === model.artifactId) ??
    artifacts.find((artifact) => artifact.filename === model.filename) ??
    artifacts.find(
      (artifact) =>
        getModelNameFromFilename(artifact.filename) === model.modelName,
    )
  );
}

function buildPipelineGraph(
  pipeline: PipelineRun,
  artifacts: Artifact[],
): {
  nodes: PositionedPipelineNode[];
  edges: PipelineEdge[];
  width: number;
  height: number;
} {
  const modelByName = new Map(
    pipeline.models.map((model) => [model.modelName, model]),
  );
  const tableByName = new Map(
    pipeline.tables.map((table) => [table.tableName, table]),
  );
  const artifactByModelName = new Map(
    pipeline.models.map((model) => [
      model.modelName,
      findArtifactForModel(model, artifacts),
    ]),
  );

  const hasRealDependencies = pipeline.models.some((model) =>
    model.dependencies.some((dependency) => modelByName.has(dependency)),
  );

  const levelCache = new Map<string, number>();
  const visiting = new Set<string>();

  function getLevel(model: PipelineModelStep, fallbackIndex: number): number {
    if (!hasRealDependencies) return fallbackIndex;

    const cached = levelCache.get(model.modelName);
    if (cached !== undefined) return cached;

    if (visiting.has(model.modelName)) {
      return fallbackIndex;
    }

    visiting.add(model.modelName);

    const dependencyLevels = model.dependencies
      .map((dependency) => modelByName.get(dependency))
      .filter((dependencyModel): dependencyModel is PipelineModelStep =>
        Boolean(dependencyModel),
      )
      .map((dependencyModel) => getLevel(dependencyModel, fallbackIndex));

    visiting.delete(model.modelName);

    const level = dependencyLevels.length
      ? Math.max(...dependencyLevels) + 1
      : 0;
    levelCache.set(model.modelName, level);
    return level;
  }

  const layered = pipeline.models.map((model, index) => ({
    model,
    index,
    level: getLevel(model, index),
  }));

  const nodesByLevel = new Map<number, typeof layered>();

  layered.forEach((item) => {
    const current = nodesByLevel.get(item.level) ?? [];
    current.push(item);
    nodesByLevel.set(item.level, current);
  });

  const positioned: PositionedPipelineNode[] = [];

  Array.from(nodesByLevel.entries())
    .sort(([levelA], [levelB]) => levelA - levelB)
    .forEach(([level, items]) => {
      items
        .sort((itemA, itemB) => itemA.index - itemB.index)
        .forEach((item, rowIndex) => {
          positioned.push({
            ...item.model,
            x: CANVAS_PADDING_X + level * LEVEL_GAP,
            y: CANVAS_PADDING_Y + rowIndex * ROW_GAP,
            layer: level,
            table: tableByName.get(item.model.modelName),
            artifact: artifactByModelName.get(item.model.modelName),
          });
        });
    });

  const positionedByName = new Map(
    positioned.map((node) => [node.modelName, node]),
  );
  const edges: PipelineEdge[] = [];

  if (hasRealDependencies) {
    positioned.forEach((node) => {
      node.dependencies.forEach((dependency) => {
        if (!positionedByName.has(dependency)) return;

        edges.push({
          id: `${dependency}__to__${node.modelName}`,
          from: dependency,
          to: node.modelName,
          label: "depends on",
        });
      });
    });
  } else {
    positioned
      .slice()
      .sort((nodeA, nodeB) => nodeA.layer - nodeB.layer)
      .forEach((node, index, orderedNodes) => {
        const nextNode = orderedNodes[index + 1];
        if (!nextNode) return;

        edges.push({
          id: `${node.modelName}__to__${nextNode.modelName}`,
          from: node.modelName,
          to: nextNode.modelName,
          label: "next",
        });
      });
  }

  const maxX = positioned.reduce(
    (max, node) => Math.max(max, node.x + NODE_WIDTH),
    0,
  );
  const maxY = positioned.reduce(
    (max, node) => Math.max(max, node.y + NODE_HEIGHT),
    0,
  );

  return {
    nodes: positioned,
    edges,
    width: Math.max(MIN_CANVAS_WIDTH, maxX + CANVAS_PADDING_X),
    height: Math.max(MIN_CANVAS_HEIGHT, maxY + CANVAS_PADDING_Y),
  };
}

function edgePath(
  fromNode: PositionedPipelineNode,
  toNode: PositionedPipelineNode,
) {
  const fromX = fromNode.x + NODE_WIDTH;
  const fromY = fromNode.y + NODE_HEIGHT / 2;
  const toX = toNode.x;
  const toY = toNode.y + NODE_HEIGHT / 2;
  const midX = fromX + (toX - fromX) / 2;

  return `M ${fromX} ${fromY} C ${midX} ${fromY}, ${midX} ${toY}, ${toX} ${toY}`;
}

function PipelineEmptyState({
  onOpenArtifacts,
}: {
  onOpenArtifacts: () => void;
}) {
  return (
    <section className="pipeline-empty-state pipeline-visual-empty-state">
      <div className="empty-state cinematic-empty">
        <div className="empty-icon">▶</div>
        <strong>No executable pipeline yet</strong>
        <p>
          Generate SQL model artifacts first. Then come back here to materialize
          the generated pipeline into a temporary demo data mart.
        </p>
        <button type="button" onClick={onOpenArtifacts}>
          Review artifacts
        </button>
      </div>
    </section>
  );
}

function PipelinePreviewTable({
  preview,
}: {
  preview: PipelineTablePreview | null;
}) {
  if (!preview) {
    return (
      <div className="pipeline-preview-empty pipeline-drawer-empty">
        <strong>No table preview selected</strong>
        <p>
          Select a completed SQL component with an output table to preview rows.
        </p>
      </div>
    );
  }

  return (
    <div className="pipeline-preview-table-wrap pipeline-visual-preview-table-wrap">
      <table className="pipeline-preview-table">
        <thead>
          <tr>
            {preview.columns.map((column) => (
              <th key={column}>{column}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {preview.rows.map((row, rowIndex) => (
            <tr key={`${preview.tableName}_${rowIndex}`}>
              {preview.columns.map((column) => (
                <td key={`${preview.tableName}_${rowIndex}_${column}`}>
                  {formatValue(row[column])}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function PipelineNodeCard({
  node,
  selected,
  runId,
  onSelect,
  onPreview,
  onViewSql,
}: {
  node: PositionedPipelineNode;
  selected: boolean;
  runId: string;
  onSelect: (node: PositionedPipelineNode) => void;
  onPreview: (node: PositionedPipelineNode) => void;
  onViewSql: (node: PositionedPipelineNode) => void;
}) {
  const canPreview = Boolean(node.table && node.status === "completed");

  return (
    <article
      className={`pipeline-flow-node pipeline-flow-node-${node.status} ${selected ? "selected" : ""}`}
      style={{ left: node.x, top: node.y }}
    >
      <button
        type="button"
        className="pipeline-flow-node-main"
        onClick={() => onSelect(node)}
      >
        <div className="pipeline-flow-node-topline">
          <span>SQL model</span>
          <em>{formatStepStatus(node.status)}</em>
        </div>

        <strong title={node.modelName}>{node.modelName}</strong>
        <small title={node.filename}>{node.filename}</small>

        <div className="pipeline-flow-node-meta">
          {node.rowCount !== null && node.rowCount !== undefined ? (
            <span>{node.rowCount.toLocaleString()} rows</span>
          ) : (
            <span>
              {node.table
                ? `${node.table.rowCount.toLocaleString()} rows`
                : "not materialized"}
            </span>
          )}
          {node.dependencies.length > 0 && (
            <span>{node.dependencies.length} deps</span>
          )}
        </div>
      </button>

      {node.error && <p className="pipeline-flow-node-error">{node.error}</p>}

      <div className="pipeline-flow-node-actions">
        <button type="button" onClick={() => onPreview(node)} disabled={!canPreview}>
          Preview
        </button>

        <button type="button" onClick={() => onViewSql(node)}>
          SQL
        </button>

        {node.table ? (
          <a href={pipelineTableCsvUrl(runId, node.table.tableName)}>CSV</a>
        ) : (
          <span>CSV</span>
        )}
      </div>
    </article>
  );
}

function PipelineCanvas({
  runId,
  graph,
  zoom,
  selectedModelName,
  onSelectNode,
  onPreviewNode,
  onViewSqlNode,
}: {
  runId: string;
  graph: ReturnType<typeof buildPipelineGraph>;
  zoom: number;
  selectedModelName: string | null;
  onSelectNode: (node: PositionedPipelineNode) => void;
  onPreviewNode: (node: PositionedPipelineNode) => void;
  onViewSqlNode: (node: PositionedPipelineNode) => void;
}) {
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const dragState = useRef({
    active: false,
    pointerId: 0,
    startX: 0,
    startY: 0,
    scrollLeft: 0,
    scrollTop: 0,
  });
  const [isPanning, setIsPanning] = useState(false);

  const nodeByName = new Map(graph.nodes.map((node) => [node.modelName, node]));

  function handlePointerDown(event: PointerEvent<HTMLDivElement>) {
    if (event.button !== 0) return;

    const target = event.target as HTMLElement;

    if (
      target.closest(".pipeline-flow-node") ||
      target.closest(".pipeline-floating-toolbar") ||
      target.closest(".pipeline-detail-drawer")
    ) {
      return;
    }

    const scrollElement = scrollRef.current;
    if (!scrollElement) return;

    dragState.current = {
      active: true,
      pointerId: event.pointerId,
      startX: event.clientX,
      startY: event.clientY,
      scrollLeft: scrollElement.scrollLeft,
      scrollTop: scrollElement.scrollTop,
    };

    setIsPanning(true);
    event.currentTarget.setPointerCapture(event.pointerId);
  }

  function handlePointerMove(event: PointerEvent<HTMLDivElement>) {
    if (!dragState.current.active) return;

    const scrollElement = scrollRef.current;
    if (!scrollElement) return;

    const deltaX = event.clientX - dragState.current.startX;
    const deltaY = event.clientY - dragState.current.startY;

    scrollElement.scrollLeft = dragState.current.scrollLeft - deltaX;
    scrollElement.scrollTop = dragState.current.scrollTop - deltaY;
  }

  function stopPanning(event: PointerEvent<HTMLDivElement>) {
    if (!dragState.current.active) return;

    dragState.current.active = false;
    setIsPanning(false);

    try {
      event.currentTarget.releasePointerCapture(dragState.current.pointerId);
    } catch {
      // Pointer capture may already be released.
    }
  }

  return (
    <div
      ref={scrollRef}
      className={isPanning ? "pipeline-canvas-scroll is-panning" : "pipeline-canvas-scroll"}
      onPointerDown={handlePointerDown}
      onPointerMove={handlePointerMove}
      onPointerUp={stopPanning}
      onPointerCancel={stopPanning}
    >
      <div
        className="pipeline-canvas-spacer"
        style={{ width: graph.width * zoom + 240, height: graph.height * zoom + 180 }}
      >
        <div
          className="pipeline-canvas"
          style={{
            width: graph.width,
            height: graph.height,
            transform: `scale(${zoom})`,
          }}
        >
          <svg
            className="pipeline-edge-layer"
            viewBox={`0 0 ${graph.width} ${graph.height}`}
            aria-hidden="true"
          >
            <defs>
              <marker
                id="pipeline-edge-arrow"
                viewBox="0 0 10 10"
                refX="9"
                refY="5"
                markerWidth="7"
                markerHeight="7"
                orient="auto-start-reverse"
              >
                <path d="M 0 0 L 10 5 L 0 10 z" />
              </marker>
            </defs>

            {graph.edges.map((edge) => {
              const fromNode = nodeByName.get(edge.from);
              const toNode = nodeByName.get(edge.to);

              if (!fromNode || !toNode) return null;

              const pathId = `pipeline-edge-path-${edge.id}`;

              return (
                <g key={edge.id} className="pipeline-edge-group">
                  <path
                    id={pathId}
                    className="pipeline-edge-label-path"
                    d={edgePath(fromNode, toNode)}
                  />
                  <path className="pipeline-edge-line" d={edgePath(fromNode, toNode)} />
                  <text>
                    <textPath href={`#${pathId}`} startOffset="50%">
                      {edge.label}
                    </textPath>
                  </text>
                </g>
              );
            })}
          </svg>

          {graph.nodes.map((node) => (
            <PipelineNodeCard
              key={node.modelName}
              node={node}
              selected={selectedModelName === node.modelName}
              runId={runId}
              onSelect={onSelectNode}
              onPreview={onPreviewNode}
              onViewSql={onViewSqlNode}
            />
          ))}
        </div>
      </div>
    </div>
  );
}

function PipelineAccordionSection({
  title,
  meta,
  expanded,
  onToggle,
  children,
}: {
  title: string;
  meta?: string;
  expanded: boolean;
  onToggle: () => void;
  children: ReactNode;
}) {
  return (
    <section className="pipeline-accordion-section">
      <button
        type="button"
        className="pipeline-accordion-header"
        aria-expanded={expanded}
        onClick={onToggle}
      >
        <span className={expanded ? "pipeline-accordion-caret expanded" : "pipeline-accordion-caret"}>
          ▸
        </span>
        <strong>{title}</strong>
        {meta && <em>{meta}</em>}
      </button>

      {expanded && <div className="pipeline-accordion-body">{children}</div>}
    </section>
  );
}

function PipelineDetailDrawer({
  open,
  runId,
  node,
  preview,
  previewLoading,
  expandedSections,
  sqlContent,
  sqlLoading,
  sqlError,
  onClose,
  onPreview,
  onToggleSection,
}: {
  open: boolean;
  runId: string;
  node: PositionedPipelineNode | null;
  preview: PipelineTablePreview | null;
  previewLoading: boolean;
  expandedSections: PipelineDrawerSections;
  sqlContent: string | null;
  sqlLoading: boolean;
  sqlError: string | null;
  onClose: () => void;
  onPreview: (node: PositionedPipelineNode) => void;
  onToggleSection: (section: keyof PipelineDrawerSections) => void;
}) {
  const fallbackSqlPreview = getFallbackArtifactSqlPreview(node?.artifact);
  const sqlPreview = sqlContent ?? fallbackSqlPreview;
  const nodePreview = node?.table && preview?.tableName === node.table.tableName ? preview : null;

  const rowLabel = node?.table
    ? `${node.table.rowCount.toLocaleString()} rows`
    : node?.rowCount !== null && node?.rowCount !== undefined
      ? `${node.rowCount.toLocaleString()} rows`
      : "not materialized";

  const columnLabel = node?.table ? `${node.table.columns.length} columns` : "no output table";

  const outputSummary = node?.table
    ? `${node.table.tableName} · ${node.table.rowCount.toLocaleString()} rows · ${node.table.columns.length} columns`
    : "Run the pipeline to materialize this component.";

  return (
    <aside className={open ? "pipeline-detail-drawer open" : "pipeline-detail-drawer"}>
      <div className="pipeline-detail-header pipeline-detail-header-compact">
        <div>
          <span className="section-kicker">Component details</span>
          <strong>{node?.modelName ?? "Select a SQL model"}</strong>
        </div>
        <button type="button" onClick={onClose} aria-label="Hide pipeline details">
          ×
        </button>
      </div>

      {!node ? (
        <p className="muted-copy">
          Select a component on the canvas to inspect SQL, status, output, and downloads.
        </p>
      ) : (
        <>
          <section className="pipeline-component-summary-card">
            <div className="pipeline-component-status-line">
              <span className={`pipeline-compact-status pipeline-compact-status-${node.status}`}>
                {formatStepStatus(node.status)}
              </span>
              <span>{rowLabel}</span>
              <span>{columnLabel}</span>
            </div>

            <div className="pipeline-component-compact-grid">
              <span>SQL</span>
              <strong title={node.filename}>{node.filename}</strong>

              <span>Depends on</span>
              <strong title={node.dependencies.join(", ") || "No upstream model"}>
                {node.dependencies.length ? node.dependencies.join(", ") : "No upstream model"}
              </strong>

              <span>Output</span>
              <strong title={outputSummary}>{outputSummary}</strong>
            </div>

            <div className="pipeline-component-actions-row">
              <button type="button" onClick={() => onPreview(node)} disabled={!node.table}>
                Preview table
              </button>
              {node.table && <a href={pipelineTableCsvUrl(runId, node.table.tableName)}>Download CSV</a>}
            </div>
          </section>

          {node.error && <div className="pipeline-error-banner">{node.error}</div>}

          <PipelineAccordionSection
            title="SQL artifact preview"
            meta={expandedSections.sql ? "Hide SQL" : "Show SQL"}
            expanded={expandedSections.sql}
            onToggle={() => onToggleSection("sql")}
          >
            {sqlLoading ? (
              <div className="pipeline-preview-empty pipeline-drawer-empty">
                <strong>Loading full SQL...</strong>
                <p>Fetching the complete artifact content from the backend.</p>
              </div>
            ) : (
              <>
                {sqlError && (
                  <div className="pipeline-error-banner">
                    {sqlError}
                    <br />
                    Showing fallback preview content.
                  </div>
                )}

                <pre className="pipeline-sql-preview">
                  <code>{sqlPreview}</code>
                </pre>
              </>
            )}
          </PipelineAccordionSection>

          <PipelineAccordionSection
            title="Table preview"
            meta={
              node.table
                ? `${node.table.rowCount.toLocaleString()} rows · ${node.table.columns.length} columns`
                : "No table yet"
            }
            expanded={expandedSections.table}
            onToggle={() => onToggleSection("table")}
          >
            {previewLoading ? (
              <div className="pipeline-preview-empty pipeline-drawer-empty">
                <strong>Loading preview...</strong>
              </div>
            ) : node.table ? (
              nodePreview ? (
                <PipelinePreviewTable preview={nodePreview} />
              ) : (
                <div className="pipeline-preview-empty pipeline-drawer-empty">
                  <strong>Preview is not loaded yet</strong>
                  <p>Click Preview table to load the first rows from this output table.</p>
                  <button type="button" onClick={() => onPreview(node)}>
                    Load preview
                  </button>
                </div>
              )
            ) : (
              <PipelinePreviewTable preview={null} />
            )}
          </PipelineAccordionSection>
        </>
      )}
    </aside>
  );
}

export function PipelinePanel({
  runId,
  artifacts,
  onOpenArtifacts,
}: PipelinePanelProps) {
  const [pipeline, setPipeline] = useState<PipelineRun | null>(null);
  const [preview, setPreview] = useState<PipelineTablePreview | null>(null);
  const [selectedModelName, setSelectedModelName] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [executing, setExecuting] = useState(false);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [zoom, setZoom] = useState(DEFAULT_ZOOM);
  const [showDetails, setShowDetails] = useState(true);
  const [expandedSections, setExpandedSections] = useState<PipelineDrawerSections>({
    sql: false,
    table: false,
  });
  const [fullSqlByArtifactId, setFullSqlByArtifactId] = useState<Record<string, string>>({});
  const [sqlLoadingArtifactId, setSqlLoadingArtifactId] = useState<string | null>(null);
  const [sqlLoadErrorByArtifactId, setSqlLoadErrorByArtifactId] = useState<Record<string, string>>({});

  const sqlArtifactCount = useMemo(() => getSqlArtifactCount(artifacts), [artifacts]);

  useEffect(() => {
    const activeArtifactIds = new Set(artifacts.map((artifact) => artifact.id));

    setFullSqlByArtifactId((current) => {
      const next: Record<string, string> = {};

      for (const [artifactId, content] of Object.entries(current)) {
        if (activeArtifactIds.has(artifactId)) {
          next[artifactId] = content;
        }
      }

      return next;
    });

    setSqlLoadErrorByArtifactId((current) => {
      const next: Record<string, string> = {};

      for (const [artifactId, message] of Object.entries(current)) {
        if (activeArtifactIds.has(artifactId)) {
          next[artifactId] = message;
        }
      }

      return next;
    });

    setSqlLoadingArtifactId((current) => {
      if (!current) return null;
      return activeArtifactIds.has(current) ? current : null;
    });
  }, [artifacts]);

  useEffect(() => {
    let active = true;

    if (!runId) {
      setPipeline(null);
      setPreview(null);
      setSelectedModelName(null);
      setExpandedSections({ sql: false, table: false });
      setFullSqlByArtifactId({});
      setSqlLoadErrorByArtifactId({});
      setSqlLoadingArtifactId(null);
      setError(null);
      return;
    }

    setLoading(true);
    setError(null);

    getPipelineStatus(runId)
      .then((status) => {
        if (!active) return;
        setPipeline(status);
        setSelectedModelName((current) => current ?? status.models[0]?.modelName ?? null);
      })
      .catch((loadError: unknown) => {
        if (!active) return;
        setError(loadError instanceof Error ? loadError.message : String(loadError));
      })
      .finally(() => {
        if (!active) return;
        setLoading(false);
      });

    return () => {
      active = false;
    };
  }, [runId]);

  const graph = useMemo(() => {
    if (!pipeline) return null;
    return buildPipelineGraph(pipeline, artifacts);
  }, [artifacts, pipeline]);

  const selectedNode =
    graph?.nodes.find((node) => node.modelName === selectedModelName) ??
    graph?.nodes[0] ??
    null;

  const selectedArtifactId = selectedNode?.artifact?.id ?? null;
  const selectedSqlContent = selectedArtifactId ? fullSqlByArtifactId[selectedArtifactId] ?? null : null;
  const selectedSqlLoading = Boolean(selectedArtifactId && sqlLoadingArtifactId === selectedArtifactId);
  const selectedSqlError = selectedArtifactId ? sqlLoadErrorByArtifactId[selectedArtifactId] ?? null : null;

  useEffect(() => {
    if (!graph || graph.nodes.length === 0) {
      setSelectedModelName(null);
      return;
    }

    if (!graph.nodes.some((node) => node.modelName === selectedModelName)) {
      setSelectedModelName(graph.nodes[0].modelName);
    }
  }, [graph, selectedModelName]);

  async function loadFullSqlForNode(node: PositionedPipelineNode): Promise<string | null> {
    const artifact = node.artifact;

    if (!artifact) {
      return null;
    }

    if (typeof artifact.content === "string") {
      setFullSqlByArtifactId((current) => ({
        ...current,
        [artifact.id]: artifact.content ?? "",
      }));
      return artifact.content;
    }

    const cached = fullSqlByArtifactId[artifact.id];
    if (cached !== undefined) {
      return cached;
    }

    setSqlLoadingArtifactId(artifact.id);
    setSqlLoadErrorByArtifactId((current) => {
      const next = { ...current };
      delete next[artifact.id];
      return next;
    });

    try {
      const response = await getArtifactContent(artifact.runId, artifact.id);
      const content = response.content ?? "";

      setFullSqlByArtifactId((current) => ({
        ...current,
        [artifact.id]: content,
      }));

      return content;
    } catch (sqlError) {
      setSqlLoadErrorByArtifactId((current) => ({
        ...current,
        [artifact.id]: getErrorMessage(sqlError),
      }));
      return null;
    } finally {
      setSqlLoadingArtifactId((current) => (current === artifact.id ? null : current));
    }
  }

  async function loadPreviewForNode(node: PositionedPipelineNode) {
    if (!runId || !node.table) {
      setPreview(null);
      return;
    }

    setPreviewLoading(true);
    setShowDetails(true);
    setSelectedModelName(node.modelName);
    setExpandedSections({ sql: false, table: true });

    try {
      const tablePreview = await getPipelineTablePreview(runId, node.table.tableName, 50);
      setPreview(tablePreview);
    } catch {
      setPreview(null);
    } finally {
      setPreviewLoading(false);
    }
  }

  function selectNodeForDetails(node: PositionedPipelineNode) {
    setSelectedModelName(node.modelName);
    setShowDetails(true);
    setPreview(null);
    setPreviewLoading(false);
    setExpandedSections({ sql: false, table: false });
  }

  function openSqlForNode(node: PositionedPipelineNode) {
    setSelectedModelName(node.modelName);
    setShowDetails(true);
    setPreview(null);
    setPreviewLoading(false);
    setExpandedSections({ sql: true, table: false });
    void loadFullSqlForNode(node);
  }

  function toggleDrawerSection(section: keyof PipelineDrawerSections) {
    const shouldExpand = !expandedSections[section];

    setExpandedSections((current) => ({
      ...current,
      [section]: !current[section],
    }));

    if (section === "sql" && shouldExpand && selectedNode) {
      void loadFullSqlForNode(selectedNode);
    }
  }

  async function handleExecutePipeline() {
    if (!runId) return;

    setExecuting(true);
    setError(null);
    setPreview(null);

    try {
      const result = await executePipeline(runId);
      setPipeline(result);
      setSelectedModelName(result.models[0]?.modelName ?? null);

      const firstCompletedModel = result.models.find((model) =>
        result.tables.some((table) => table.tableName === model.modelName),
      );

      if (firstCompletedModel) {
        const updatedGraph = buildPipelineGraph(result, artifacts);
        const node = updatedGraph.nodes.find((item) => item.modelName === firstCompletedModel.modelName);
        if (node) {
          await loadPreviewForNode(node);
        }
      }
    } catch (executeError) {
      setError(executeError instanceof Error ? executeError.message : String(executeError));
    } finally {
      setExecuting(false);
    }
  }

  function zoomIn() {
    setZoom((current) => clampZoom(current + ZOOM_STEP));
  }

  function zoomOut() {
    setZoom((current) => clampZoom(current - ZOOM_STEP));
  }

  function resetZoom() {
    setZoom(DEFAULT_ZOOM);
  }

  if (!runId) {
    return <PipelineEmptyState onOpenArtifacts={onOpenArtifacts} />;
  }

  const isPipelineReady = Boolean(pipeline && pipeline.status !== "not_ready");
  const canRun = sqlArtifactCount > 0 && !executing;

  if (!loading && !isPipelineReady) {
    return <PipelineEmptyState onOpenArtifacts={onOpenArtifacts} />;
  }

  return (
    <section className="pipeline-visual-page-shell">
      <header className="pipeline-floating-header">
        <div className="pipeline-floating-title">
          <span className="section-kicker">Executable demo pipeline</span>
          <strong>Generated SQL lineage</strong>
          <p>
            Run generated dbt-style SQL components into a temporary per-run SQLite data mart.
          </p>
        </div>

        <div className="pipeline-floating-summary" aria-label="Pipeline summary">
          <span>{pipeline ? formatStatus(pipeline.status) : loading ? "Loading" : "Not loaded"}</span>
          <span>{sqlArtifactCount} SQL models</span>
          <span>{pipeline?.tables.length ?? 0} output tables</span>
        </div>

        <div className="pipeline-floating-actions">
          <button type="button" onClick={handleExecutePipeline} disabled={!canRun}>
            {executing ? "Running..." : pipeline?.status === "completed" ? "Run again" : "Run pipeline"}
          </button>
          {pipeline?.tables.length ? (
            <a href={pipelineZipUrl(runId)} className="pipeline-download-all">
              Download CSV ZIP
            </a>
          ) : null}
        </div>
      </header>

      {(error || pipeline?.error) && (
        <div className="pipeline-floating-error">{error ?? pipeline?.error}</div>
      )}

      <div className="pipeline-fullscreen-canvas">
        {graph && graph.nodes.length > 0 ? (
          <PipelineCanvas
            runId={runId}
            graph={graph}
            zoom={zoom}
            selectedModelName={selectedNode?.modelName ?? null}
            onSelectNode={selectNodeForDetails}
            onPreviewNode={loadPreviewForNode}
            onViewSqlNode={openSqlForNode}
          />
        ) : (
          <div className="pipeline-visual-loading">
            <div className="empty-state cinematic-empty">
              <div className="empty-icon">◎</div>
              <strong>{loading ? "Loading pipeline..." : "No SQL model components"}</strong>
              <p>The pipeline graph will appear after SQL artifacts are available.</p>
            </div>
          </div>
        )}
      </div>

      <div className="pipeline-floating-toolbar" aria-label="Pipeline canvas controls">
        <button type="button" onClick={() => setShowDetails((value) => !value)}>
          {showDetails ? "Hide details" : "Details"}
        </button>
        <span className="pipeline-toolbar-divider" />
        <button type="button" onClick={zoomOut} aria-label="Zoom out">
          −
        </button>
        <strong>{Math.round(zoom * 100)}%</strong>
        <button type="button" onClick={zoomIn} aria-label="Zoom in">
          +
        </button>
        <button type="button" onClick={resetZoom}>
          Reset
        </button>
      </div>

      <PipelineDetailDrawer
        open={showDetails}
        runId={runId}
        node={selectedNode}
        preview={preview}
        previewLoading={previewLoading}
        expandedSections={expandedSections}
        sqlContent={selectedSqlContent}
        sqlLoading={selectedSqlLoading}
        sqlError={selectedSqlError}
        onClose={() => setShowDetails(false)}
        onPreview={loadPreviewForNode}
        onToggleSection={toggleDrawerSection}
      />
    </section>
  );
}
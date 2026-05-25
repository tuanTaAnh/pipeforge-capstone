import { useEffect, useMemo, useRef, useState } from "react";

import { getDatabaseGraph } from "../../api/databaseGraphApi";
import type {
  DatabaseGraphEdge,
  DatabaseGraphNode,
  DatabaseGraphResponse
} from "../../types/databaseGraph";

type RoleFilter = "all" | "dimension" | "fact" | "source";

type PositionedNode = DatabaseGraphNode & {
  x: number;
  y: number;
};

const CANVAS_WIDTH = 1900;
const MIN_CANVAS_HEIGHT = 760;
const NODE_WIDTH = 250;
const NODE_HEIGHT = 148;
const NODE_GAP = 42;

const MIN_ZOOM = 0.45;
const MAX_ZOOM = 1.45;
const ZOOM_STEP = 0.1;
const DEFAULT_ZOOM = 0.78;

function clampZoom(value: number) {
  return Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, Number(value.toFixed(2))));
}

function formatCount(value?: number | null) {
  if (value === null || value === undefined) return "n/a";
  return new Intl.NumberFormat().format(value);
}

function formatKey(value: string | string[]) {
  if (Array.isArray(value)) return value.join(" + ");
  return value;
}

function getRoleLabel(role: string) {
  if (role === "dimension") return "Dimension";
  if (role === "fact") return "Fact";
  return role.replace(/_/g, " ");
}

function getRoleClass(role: string) {
  if (role === "dimension") return "dimension";
  if (role === "fact") return "fact";
  return "source";
}

function getNodeSearchText(node: DatabaseGraphNode) {
  return [
    node.id,
    node.label,
    node.tableName,
    node.sourceRole,
    node.businessEntity,
    node.grain,
    node.primaryKey,
    node.businessMeaning,
    ...node.columns.map((column) => column.name),
    ...node.metrics.map((metric) => metric.label),
    ...node.dimensions.map((dimension) => dimension.label),
    ...node.dataProducts.map((dataProduct) => dataProduct.label)
  ]
    .filter(Boolean)
    .join(" ")
    .toLowerCase();
}

function getCanvasHeight(nodes: DatabaseGraphNode[]) {
  const maxRoleCount = Math.max(
    1,
    nodes.filter((node) => node.sourceRole === "dimension").length,
    nodes.filter((node) => node.sourceRole === "fact").length,
    nodes.filter((node) => !["dimension", "fact"].includes(node.sourceRole)).length
  );

  return Math.max(MIN_CANVAS_HEIGHT, 120 + maxRoleCount * NODE_HEIGHT + (maxRoleCount - 1) * NODE_GAP);
}

function layoutNodes(nodes: DatabaseGraphNode[]): { nodes: PositionedNode[]; canvasHeight: number } {
  const canvasHeight = getCanvasHeight(nodes);

  const grouped = nodes.reduce<Record<string, DatabaseGraphNode[]>>((groups, node) => {
    const role = node.sourceRole || "source";
    groups[role] = groups[role] ?? [];
    groups[role].push(node);
    return groups;
  }, {});

  const dimensions = grouped.dimension ?? [];
  const facts = grouped.fact ?? [];
  const other = Object.entries(grouped)
    .filter(([role]) => !["dimension", "fact"].includes(role))
    .flatMap(([, roleNodes]) => roleNodes);

  const placeColumn = (columnNodes: DatabaseGraphNode[], x: number): PositionedNode[] => {
    if (columnNodes.length === 0) return [];

    const totalHeight = columnNodes.length * NODE_HEIGHT + (columnNodes.length - 1) * NODE_GAP;
    const startY = Math.max(72, (canvasHeight - totalHeight) / 2);

    return columnNodes.map((node, index) => ({
      ...node,
      x,
      y: startY + index * (NODE_HEIGHT + NODE_GAP)
    }));
  };

  return {
    canvasHeight,
    nodes: [
      ...placeColumn(dimensions, 90),
      ...placeColumn(other, 820),
      ...placeColumn(facts, 1500)
    ]
  };
}

function edgePath(fromNode: PositionedNode, toNode: PositionedNode) {
  const fromX = fromNode.x + NODE_WIDTH;
  const fromY = fromNode.y + NODE_HEIGHT / 2;
  const toX = toNode.x;
  const toY = toNode.y + NODE_HEIGHT / 2;
  const midX = fromX + (toX - fromX) / 2;

  return `M ${fromX} ${fromY} C ${midX} ${fromY}, ${midX} ${toY}, ${toX} ${toY}`;
}

function DatabaseNodeCard({
  node,
  selected,
  onSelect
}: {
  node: PositionedNode;
  selected: boolean;
  onSelect: (node: DatabaseGraphNode) => void;
}) {
  const previewColumns = node.columns.slice(0, 4);

  return (
    <button
      type="button"
      className={`database-node-card database-node-${getRoleClass(node.sourceRole)} ${
        selected ? "selected" : ""
      }`}
      style={{ left: node.x, top: node.y }}
      onClick={() => onSelect(node)}
    >
      <div className="database-node-topline">
        <span>{getRoleLabel(node.sourceRole)}</span>
        <em>{formatCount(node.rowCount)} rows</em>
      </div>

      <strong title={node.label}>{node.label}</strong>
      <small title={node.grain ?? node.businessEntity ?? "database source"}>
        {node.grain ?? node.businessEntity ?? "database source"}
      </small>

      <ul>
        {previewColumns.map((column) => (
          <li key={column.name}>
            <span>{column.isPrimaryKey ? "◆" : column.reference ? "↗" : "•"}</span>
            <code title={column.name}>{column.name}</code>
          </li>
        ))}
      </ul>
    </button>
  );
}

function DatabaseExplorerDrawer({
  open,
  graph,
  filteredNodes,
  selectedNodeId,
  query,
  roleFilter,
  onClose,
  onQueryChange,
  onRoleFilterChange,
  onSelectNode
}: {
  open: boolean;
  graph: DatabaseGraphResponse;
  filteredNodes: DatabaseGraphNode[];
  selectedNodeId: string | null;
  query: string;
  roleFilter: RoleFilter;
  onClose: () => void;
  onQueryChange: (query: string) => void;
  onRoleFilterChange: (role: RoleFilter) => void;
  onSelectNode: (nodeId: string) => void;
}) {
  return (
    <aside className={open ? "database-explorer-drawer open" : "database-explorer-drawer"}>
      <div className="database-drawer-header">
        <div>
          <span className="section-kicker">Search schema</span>
          <strong>Tables & columns</strong>
        </div>
        <button type="button" onClick={onClose} aria-label="Hide schema explorer">
          ×
        </button>
      </div>

      <div className="database-toolbar">
        <label htmlFor="database-search">Search</label>
        <input
          id="database-search"
          type="search"
          value={query}
          onChange={(event) => onQueryChange(event.target.value)}
          placeholder="Search tables, columns, metrics..."
        />
      </div>

      <div className="database-filter-row" aria-label="Filter database tables">
        {(["all", "dimension", "fact"] as RoleFilter[]).map((role) => (
          <button
            key={role}
            type="button"
            className={roleFilter === role ? "active" : ""}
            onClick={() => onRoleFilterChange(role)}
          >
            {role === "all" ? "All" : getRoleLabel(role)}
          </button>
        ))}
      </div>

      <div className="database-source-list">
        {filteredNodes.map((node) => (
          <button
            key={node.id}
            type="button"
            className={selectedNodeId === node.id ? "active" : ""}
            onClick={() => onSelectNode(node.id)}
          >
            <span>{node.label}</span>
            <small>
              {getRoleLabel(node.sourceRole)} · {formatCount(node.rowCount)} rows
            </small>
          </button>
        ))}
      </div>

      {graph.warnings.length > 0 && (
        <div className="database-warning-box">
          <strong>Metadata warnings</strong>
          <ul>
            {graph.warnings.slice(0, 3).map((warning) => (
              <li key={warning}>{warning}</li>
            ))}
          </ul>
        </div>
      )}
    </aside>
  );
}

function DatabaseDetailsDrawer({
  open,
  node,
  graph,
  onClose
}: {
  open: boolean;
  node: DatabaseGraphNode | null;
  graph: DatabaseGraphResponse;
  onClose: () => void;
}) {
  const outgoingEdges = node ? graph.edges.filter((edge) => edge.from === node.id) : [];
  const incomingEdges = node ? graph.edges.filter((edge) => edge.to === node.id) : [];
  const relationships = [...incomingEdges, ...outgoingEdges];

  return (
    <aside className={open ? "database-detail-drawer open" : "database-detail-drawer"}>
      <div className="database-drawer-header">
        <div>
          <span className="section-kicker">Table details</span>
          <strong>{node ? node.label : "Select a table"}</strong>
        </div>
        <button type="button" onClick={onClose} aria-label="Hide table details">
          ×
        </button>
      </div>

      {!node ? (
        <p className="muted-copy">
          Choose a table in the map to inspect columns, relationships, metrics,
          and data products.
        </p>
      ) : (
        <>
          <div className="database-detail-heading">
            <p>{node.businessMeaning ?? node.grain ?? "No business description available."}</p>
          </div>

          <div className="database-detail-stats">
            <span>{getRoleLabel(node.sourceRole)}</span>
            <span>{formatCount(node.rowCount)} rows</span>
            <span>PK: {node.primaryKey ?? "n/a"}</span>
          </div>

          <section className="database-detail-section">
            <h4>Columns</h4>
            <div className="database-column-list">
              {node.columns.map((column) => (
                <article key={column.name} className="database-column-row">
                  <div>
                    <strong>
                      {column.name}
                      {column.isPrimaryKey ? " · PK" : ""}
                      {column.reference ? " · FK" : ""}
                    </strong>
                    <span>{column.description ?? "No description available."}</span>
                  </div>
                  <em>{column.type ?? "unknown"}</em>
                </article>
              ))}
            </div>
          </section>

          <section className="database-detail-section">
            <h4>Relationships</h4>
            {relationships.length === 0 ? (
              <p className="muted-copy">No configured relationships for this table.</p>
            ) : (
              <div className="database-chip-list">
                {relationships.map((edge) => {
                  const isOutgoing = edge.from === node.id;
                  const otherTable = isOutgoing ? edge.to : edge.from;

                  return (
                    <span key={edge.id}>
                      {isOutgoing ? "to" : "from"} {otherTable} ·{" "}
                      {formatKey(isOutgoing ? edge.fromColumn : edge.toColumn)}
                    </span>
                  );
                })}
              </div>
            )}
          </section>

          <section className="database-detail-section">
            <h4>Semantic usage</h4>

            <div className="database-detail-subsection">
              <strong>Metrics</strong>
              {node.metrics.length === 0 ? (
                <p className="muted-copy">No metrics directly use this table.</p>
              ) : (
                <div className="database-chip-list">
                  {node.metrics.map((metric) => (
                    <span key={metric.id}>{metric.label}</span>
                  ))}
                </div>
              )}
            </div>

            <div className="database-detail-subsection">
              <strong>Data products</strong>
              {node.dataProducts.length === 0 ? (
                <p className="muted-copy">No data product contracts currently include this table.</p>
              ) : (
                <div className="database-chip-list">
                  {node.dataProducts.map((dataProduct) => (
                    <span key={dataProduct.id}>{dataProduct.label}</span>
                  ))}
                </div>
              )}
            </div>
          </section>
        </>
      )}
    </aside>
  );
}

function DatabaseGraphCanvas({
  nodes,
  edges,
  canvasHeight,
  zoom,
  selectedNodeId,
  onSelectNode
}: {
  nodes: PositionedNode[];
  edges: DatabaseGraphEdge[];
  canvasHeight: number;
  zoom: number;
  selectedNodeId: string | null;
  onSelectNode: (node: DatabaseGraphNode) => void;
}) {
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const dragState = useRef({
    active: false,
    pointerId: 0,
    startX: 0,
    startY: 0,
    scrollLeft: 0,
    scrollTop: 0
  });

  const [isPanning, setIsPanning] = useState(false);

  const nodeById = new Map(nodes.map((node) => [node.id, node]));
  const visibleEdges = edges.filter((edge) => nodeById.has(edge.from) && nodeById.has(edge.to));

  function handlePointerDown(event: React.PointerEvent<HTMLDivElement>) {
    if (event.button !== 0) return;

    const target = event.target as HTMLElement;

    if (
      target.closest(".database-node-card") ||
      target.closest(".database-floating-toolbar") ||
      target.closest(".database-explorer-drawer") ||
      target.closest(".database-detail-drawer")
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
      scrollTop: scrollElement.scrollTop
    };

    setIsPanning(true);
    event.currentTarget.setPointerCapture(event.pointerId);
  }

  function handlePointerMove(event: React.PointerEvent<HTMLDivElement>) {
    if (!dragState.current.active) return;

    const scrollElement = scrollRef.current;
    if (!scrollElement) return;

    const deltaX = event.clientX - dragState.current.startX;
    const deltaY = event.clientY - dragState.current.startY;

    scrollElement.scrollLeft = dragState.current.scrollLeft - deltaX;
    scrollElement.scrollTop = dragState.current.scrollTop - deltaY;
  }

  function stopPanning(event: React.PointerEvent<HTMLDivElement>) {
    if (!dragState.current.active) return;

    dragState.current.active = false;
    setIsPanning(false);

    try {
      event.currentTarget.releasePointerCapture(dragState.current.pointerId);
    } catch {
      // Pointer capture may already be released by the browser.
    }
  }

  return (
    <div
      ref={scrollRef}
      className={isPanning ? "database-canvas-scroll is-panning" : "database-canvas-scroll"}
      onPointerDown={handlePointerDown}
      onPointerMove={handlePointerMove}
      onPointerUp={stopPanning}
      onPointerCancel={stopPanning}
    >
      <div
        className="database-canvas-spacer"
        style={{ width: CANVAS_WIDTH * zoom + 240, height: canvasHeight * zoom + 180 }}
      >
        <div
          className="database-canvas"
          style={{
            width: CANVAS_WIDTH,
            height: canvasHeight,
            transform: `scale(${zoom})`
          }}
        >
          <svg
            className="database-edge-layer"
            viewBox={`0 0 ${CANVAS_WIDTH} ${canvasHeight}`}
            aria-hidden="true"
          >
            <defs>
              <marker
                id="database-edge-arrow"
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

            {visibleEdges.map((edge) => {
              const fromNode = nodeById.get(edge.from);
              const toNode = nodeById.get(edge.to);

              if (!fromNode || !toNode) return null;

              const pathId = `database-edge-path-${edge.id}`;

              return (
                <g key={edge.id} className="database-edge-group">
                  <path
                    id={pathId}
                    className="database-edge-label-path"
                    d={edgePath(fromNode, toNode)}
                  />
                  <path className="database-edge-line" d={edgePath(fromNode, toNode)} />
                  <text>
                    <textPath href={`#${pathId}`} startOffset="50%">
                      {edge.relationshipType ?? "relationship"}
                    </textPath>
                  </text>
                </g>
              );
            })}
          </svg>

          {nodes.map((node) => (
            <DatabaseNodeCard
              key={node.id}
              node={node}
              selected={selectedNodeId === node.id}
              onSelect={onSelectNode}
            />
          ))}
        </div>
      </div>
    </div>
  );
}

export function DatabaseMapPanel() {
  const [graph, setGraph] = useState<DatabaseGraphResponse | null>(null);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [roleFilter, setRoleFilter] = useState<RoleFilter>("all");
  const [query, setQuery] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [showExplorer, setShowExplorer] = useState(false);
  const [showDetails, setShowDetails] = useState(false);
  const [zoom, setZoom] = useState(DEFAULT_ZOOM);

  useEffect(() => {
    let active = true;

    setLoading(true);
    setError(null);

    getDatabaseGraph()
      .then((response) => {
        if (!active) return;

        setGraph(response);
        setSelectedNodeId((current) => current ?? response.nodes[0]?.id ?? null);
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
  }, []);

  const filteredNodes = useMemo(() => {
    if (!graph) return [];

    const normalizedQuery = query.trim().toLowerCase();

    return graph.nodes.filter((node) => {
      const matchesRole = roleFilter === "all" || node.sourceRole === roleFilter;
      const matchesQuery =
        normalizedQuery.length === 0 || getNodeSearchText(node).includes(normalizedQuery);

      return matchesRole && matchesQuery;
    });
  }, [graph, query, roleFilter]);

  const layout = useMemo(() => layoutNodes(filteredNodes), [filteredNodes]);
  const positionedNodes = layout.nodes;

  const selectedNode =
    graph?.nodes.find((node) => node.id === selectedNodeId) ??
    filteredNodes[0] ??
    null;

  useEffect(() => {
    if (filteredNodes.length === 0) {
      setSelectedNodeId(null);
      return;
    }

    if (!filteredNodes.some((node) => node.id === selectedNodeId)) {
      setSelectedNodeId(filteredNodes[0].id);
    }
  }, [filteredNodes, selectedNodeId]);

  function selectNode(node: DatabaseGraphNode) {
    setSelectedNodeId(node.id);
    setShowDetails(true);
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

  if (loading) {
    return (
      <section className="database-fullscreen database-state-screen">
        <div className="empty-state cinematic-empty">
          <div className="empty-icon">◎</div>
          <strong>Loading database map...</strong>
          <p>Reading source contracts, semantic mappings, and relationships.</p>
        </div>
      </section>
    );
  }

  if (error || !graph) {
    return (
      <section className="database-fullscreen database-state-screen">
        <div className="empty-state cinematic-empty">
          <div className="empty-icon">!</div>
          <strong>Could not load database map</strong>
          <p>{error ?? "Unknown error"}</p>
        </div>
      </section>
    );
  }

  return (
    <section className="database-fullscreen">
      <header className="database-floating-header">
        <div>
          <span className="section-kicker">Database map</span>
          <strong>{graph.database.name ?? "PipeForge database"}</strong>
        </div>

        <div className="database-floating-summary" aria-label="Database summary">
          <span>{graph.summary.tableCount} tables</span>
          <span>{graph.summary.relationshipCount} joins</span>
          <span>{graph.summary.metricCount} metrics</span>
        </div>
      </header>

      <div className="database-floating-toolbar" aria-label="Database canvas controls">
        <button type="button" onClick={() => setShowExplorer((value) => !value)}>
          {showExplorer ? "Hide schema" : "Schema"}
        </button>
        <button type="button" onClick={() => setShowDetails((value) => !value)}>
          {showDetails ? "Hide details" : "Details"}
        </button>
        <span className="database-toolbar-divider" />
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

      <div className="database-fullscreen-canvas">
        <DatabaseGraphCanvas
          nodes={positionedNodes}
          edges={graph.edges}
          canvasHeight={layout.canvasHeight}
          zoom={zoom}
          selectedNodeId={selectedNode?.id ?? null}
          onSelectNode={selectNode}
        />
      </div>

      <DatabaseExplorerDrawer
        open={showExplorer}
        graph={graph}
        filteredNodes={filteredNodes}
        selectedNodeId={selectedNode?.id ?? null}
        query={query}
        roleFilter={roleFilter}
        onClose={() => setShowExplorer(false)}
        onQueryChange={setQuery}
        onRoleFilterChange={setRoleFilter}
        onSelectNode={(nodeId) => {
          setSelectedNodeId(nodeId);
          setShowDetails(true);
        }}
      />

      <DatabaseDetailsDrawer
        open={showDetails}
        node={selectedNode}
        graph={graph}
        onClose={() => setShowDetails(false)}
      />
    </section>
  );
}
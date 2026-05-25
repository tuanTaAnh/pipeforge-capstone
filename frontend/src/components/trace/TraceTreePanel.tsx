import type { RunState } from "../../types/run";
import { AgentNode } from "./AgentNode";

type Props = {
  state: RunState;
  onToggleNode: (nodeId: string) => void;
};

export function TraceTreePanel({ state, onToggleNode }: Props) {
  const totalAgents = Object.keys(state.nodes).length;

  return (
    <section className="panel trace-panel">
      <div className="panel-header">
        <div>
          <span className="section-kicker">Execution trace</span>
          <h2>Agent workflow</h2>
        </div>
        <span className="count-pill">{totalAgents} agents</span>
      </div>

      <div className="trace-tree">
        {state.rootAgentIds.length === 0 ? (
          <div className="empty-state">
            <div className="empty-icon">⌁</div>
            <strong>No trace yet</strong>
            <p>Agent steps, tool calls, and generated artifacts will appear here.</p>
          </div>
        ) : (
          state.rootAgentIds.map((nodeId) => (
            <AgentNode
              key={nodeId}
              nodeId={nodeId}
              state={state}
              onToggle={onToggleNode}
            />
          ))
        )}
      </div>
    </section>
  );
}
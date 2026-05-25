import type { ToolCall } from "../../types/event";

type Props = {
  tool: ToolCall;
};

function stringifyPayload(payload: unknown) {
  try {
    return JSON.stringify(payload, null, 2);
  } catch {
    return String(payload);
  }
}

export function ToolCallCard({ tool }: Props) {
  return (
    <article className={`tool-card tool-card-${tool.status}`}>
      <div className="tool-card-header">
        <div>
          <span>Tool call</span>
          <strong>{tool.toolName}</strong>
        </div>
        <span className={`tool-status tool-status-${tool.status}`}>
          {tool.status}
        </span>
      </div>

      {tool.input !== undefined && (
        <div className="payload-block">
          <small>Input</small>
          <pre>{stringifyPayload(tool.input)}</pre>
        </div>
      )}

      {tool.output !== undefined && (
        <div className="payload-block">
          <small>Output</small>
          <pre>{stringifyPayload(tool.output)}</pre>
        </div>
      )}
    </article>
  );
}
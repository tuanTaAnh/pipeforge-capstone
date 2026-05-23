import type { ToolCall } from "../../types/event";

type Props = {
  tool: ToolCall;
};

export function ToolCallCard({ tool }: Props) {
  return (
    <div className="event-card tool">
      <strong>Tool: {tool.toolName}</strong>
      <div className="tool-status">{tool.status}</div>

      {tool.input !== undefined && (
        <>
          <small>Input</small>
          <pre>{JSON.stringify(tool.input, null, 2)}</pre>
        </>
      )}

      {tool.output !== undefined && (
        <>
          <small>Output</small>
          <pre>{JSON.stringify(tool.output, null, 2)}</pre>
        </>
      )}
    </div>
  );
}
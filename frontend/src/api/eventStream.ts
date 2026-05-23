import { API_BASE } from "./client";
import type { AgentEvent } from "../types/event";

export function createRunEventSource(
  runId: string,
  afterSeq: number,
  onEvent: (event: AgentEvent) => void,
  onError: () => void
): EventSource {
  const source = new EventSource(
    `${API_BASE}/api/runs/${runId}/events?after=${afterSeq}`
  );

  source.onmessage = (message) => {
    const event = JSON.parse(message.data) as AgentEvent;
    onEvent(event);

    if (event.type === "done") {
      source.close();
    }
  };

  source.onerror = () => {
    source.close();
    onError();
  };

  return source;
}
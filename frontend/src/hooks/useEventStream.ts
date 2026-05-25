import { useRef } from "react";

import { createRunEventSource } from "../api/eventStream";
import type { AgentEvent } from "../types/event";

type UseEventStreamParams = {
  onEvent: (event: AgentEvent) => void;
  onDisconnected: () => void;
};

export function useEventStream({ onEvent, onDisconnected }: UseEventStreamParams) {
  const eventSourceRef = useRef<EventSource | null>(null);
  const runIdRef = useRef<string | undefined>(undefined);
  const lastSeqRef = useRef(0);

  function connect(runId: string, afterSeq = 0) {
    eventSourceRef.current?.close();

    runIdRef.current = runId;
    lastSeqRef.current = afterSeq;

    eventSourceRef.current = createRunEventSource(
      runId,
      afterSeq,
      (event) => {
        lastSeqRef.current = event.seq;
        onEvent(event);

        if (event.type === "done") {
          eventSourceRef.current?.close();
          eventSourceRef.current = null;
        }
      },
      () => {
        onDisconnected();

        window.setTimeout(() => {
          if (runIdRef.current) {
            connect(runIdRef.current, lastSeqRef.current);
          }
        }, 1500);
      }
    );
  }

  function close() {
    eventSourceRef.current?.close();
    eventSourceRef.current = null;
    runIdRef.current = undefined;
    lastSeqRef.current = 0;
  }

  return {
    connect,
    close,
    getLastSeq: () => lastSeqRef.current
  };
}
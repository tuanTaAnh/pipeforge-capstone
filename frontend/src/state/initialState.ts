import type { RunState } from "../types/run";

export const samplePrompt =
  "Help me create a monthly revenue pipeline from Stripe data.";

export function createInitialState(): RunState {
  return {
    status: "idle",
    connected: false,
    lastSeq: 0,
    nodes: {},
    rootAgentIds: [],
    chatMessages: [
      {
        id: "welcome",
        role: "system",
        text: "PipeForge turns a business analytics request into a transparent data pipeline run."
      }
    ],
    artifacts: [],
    activity: [],
    errors: []
  };
}

export const initialState: RunState = createInitialState();
import type { RunState } from "../types/run";

export const samplePrompt =
  "Our finance team needs a trusted monthly revenue dataset from Stripe for a board dashboard. We need MRR by customer segment, but we are not sure how refunds and discounts should be handled. Can you prepare this as a data product draft for our analytics team?";

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
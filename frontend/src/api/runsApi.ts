import { API_BASE } from "./client";

export async function startRun(prompt: string): Promise<{ runId: string }> {
  const response = await fetch(`${API_BASE}/api/runs`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify({ prompt })
  });

  if (!response.ok) {
    throw new Error(await response.text());
  }

  return response.json();
}

export async function submitAnswer(
  runId: string,
  questionId: string,
  answer: string
): Promise<void> {
  const response = await fetch(`${API_BASE}/api/runs/${runId}/answers`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify({ questionId, answer })
  });

  if (!response.ok) {
    throw new Error(await response.text());
  }
}

export async function retryRun(runId: string, agentId?: string): Promise<void> {
  const response = await fetch(`${API_BASE}/api/runs/${runId}/retry`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify({ agentId })
  });

  if (!response.ok) {
    throw new Error(await response.text());
  }
}
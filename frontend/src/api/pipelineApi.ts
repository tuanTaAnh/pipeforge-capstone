import { API_BASE } from "./client";
import type { PipelineRun, PipelineTablePreview } from "../types/pipeline";

async function parseJsonResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    let message = `${response.status} ${response.statusText}`;

    try {
      const body = await response.json();
      message = body.detail || message;
    } catch {
      // Keep default message when response is not JSON.
    }

    throw new Error(message);
  }

  return response.json() as Promise<T>;
}

export async function getPipelineStatus(runId: string): Promise<PipelineRun> {
  const response = await fetch(`${API_BASE}/api/runs/${runId}/pipeline`);
  return parseJsonResponse<PipelineRun>(response);
}

export async function executePipeline(runId: string): Promise<PipelineRun> {
  const response = await fetch(`${API_BASE}/api/runs/${runId}/pipeline/execute`, {
    method: "POST"
  });
  return parseJsonResponse<PipelineRun>(response);
}

export async function getPipelineTablePreview(
  runId: string,
  tableName: string,
  limit = 50
): Promise<PipelineTablePreview> {
  const response = await fetch(
    `${API_BASE}/api/runs/${runId}/pipeline/tables/${encodeURIComponent(tableName)}/preview?limit=${limit}`
  );
  return parseJsonResponse<PipelineTablePreview>(response);
}

export function pipelineTableCsvUrl(runId: string, tableName: string) {
  return `${API_BASE}/api/runs/${runId}/pipeline/tables/${encodeURIComponent(tableName)}/download.csv`;
}

export function pipelineZipUrl(runId: string) {
  return `${API_BASE}/api/runs/${runId}/pipeline/download.zip`;
}

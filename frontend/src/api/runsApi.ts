import { API_BASE } from "./client";
import type { ArtifactContentResponse } from "../types/artifact";
import type { AnswerSubmission } from "../types/run";

type RequestOptions = {
  signal?: AbortSignal;
};

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
  submission: AnswerSubmission
): Promise<void> {
  const response = await fetch(`${API_BASE}/api/runs/${runId}/answers`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify({
      questionId,
      ...submission
    })
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

export async function getArtifactContent(
  runId: string,
  artifactId: string,
  options: RequestOptions = {}
): Promise<ArtifactContentResponse> {
  const candidateUrls = [
    `${API_BASE}/api/runs/${runId}/artifacts/${artifactId}`,
    `${API_BASE}/api/runs/${runId}/artifacts/${artifactId}/content`,
    `${API_BASE}/api/artifacts/${artifactId}`,
    `${API_BASE}/api/artifacts/${artifactId}/content`
  ];

  let lastErrorMessage = "";

  for (const url of candidateUrls) {
    const response = await fetch(url, {
      method: "GET",
      signal: options.signal
    });

    if (response.ok) {
      return parseArtifactContentResponse(response);
    }

    const errorText = await response.text();
    lastErrorMessage = errorText || `${response.status} ${response.statusText}`;

    if (response.status !== 404 && response.status !== 405) {
      throw new Error(lastErrorMessage);
    }
  }

  throw new Error(
    lastErrorMessage ||
      `Failed to load artifact content for artifact ${artifactId} in run ${runId}.`
  );
}

async function parseArtifactContentResponse(
  response: Response
): Promise<ArtifactContentResponse> {
  const contentType = response.headers.get("content-type") ?? "";
  const responseText = await response.text();

  if (!responseText) {
    return { content: "" };
  }

  if (!contentType.includes("application/json")) {
    return { content: responseText };
  }

  const payload: unknown = JSON.parse(responseText);

  return normalizeArtifactContentPayload(payload);
}

function normalizeArtifactContentPayload(payload: unknown): ArtifactContentResponse {
  if (typeof payload === "string") {
    return { content: payload };
  }

  if (!payload || typeof payload !== "object") {
    return { content: String(payload ?? "") };
  }

  const record = payload as Record<string, unknown>;

  if (typeof record.content === "string") {
    return {
      ...(record as Partial<ArtifactContentResponse>),
      content: record.content
    };
  }

  if (record.artifact && typeof record.artifact === "object") {
    const artifact = record.artifact as Record<string, unknown>;

    if (typeof artifact.content === "string") {
      return {
        ...(artifact as Partial<ArtifactContentResponse>),
        content: artifact.content
      };
    }

    if (typeof artifact.contentPreview === "string") {
      return {
        ...(artifact as Partial<ArtifactContentResponse>),
        content: artifact.contentPreview
      };
    }
  }

  if (record.data && typeof record.data === "object") {
    const data = record.data as Record<string, unknown>;

    if (typeof data.content === "string") {
      return {
        ...(data as Partial<ArtifactContentResponse>),
        content: data.content
      };
    }

    if (typeof data.contentPreview === "string") {
      return {
        ...(data as Partial<ArtifactContentResponse>),
        content: data.contentPreview
      };
    }
  }

  if (typeof record.contentPreview === "string") {
    return {
      ...(record as Partial<ArtifactContentResponse>),
      content: record.contentPreview
    };
  }

  return {
    content: JSON.stringify(payload, null, 2)
  };
}
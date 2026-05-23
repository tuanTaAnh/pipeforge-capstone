export type Artifact = {
  id: string;
  runId: string;
  filename: string;
  path: string;
  type: "sql" | "yaml" | "markdown" | "json" | "text" | string;
  createdByAgentId: string;
  createdByAgentName: string;
  contentPreview: string;
};
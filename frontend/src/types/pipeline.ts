export type PipelineStatus = "not_ready" | "not_run" | "running" | "completed" | "failed";

export type PipelineStepStatus = "pending" | "running" | "completed" | "failed";

export type PipelineModelStep = {
  filename: string;
  modelName: string;
  artifactId: string;
  dependencies: string[];
  status: PipelineStepStatus;
  rowCount?: number | null;
  error?: string | null;
};

export type PipelineTable = {
  tableName: string;
  rowCount: number;
  columns: string[];
};

export type PipelineRun = {
  runId: string;
  status: PipelineStatus;
  martPath: string;
  startedAt?: string | null;
  completedAt?: string | null;
  models: PipelineModelStep[];
  tables: PipelineTable[];
  error?: string | null;
};

export type PipelineTablePreview = {
  runId: string;
  tableName: string;
  columns: string[];
  rows: Record<string, unknown>[];
  rowCount: number;
  limit: number;
};

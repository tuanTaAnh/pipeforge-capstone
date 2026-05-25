import { API_BASE } from "./client";
import type { DatabaseGraphResponse } from "../types/databaseGraph";

export async function getDatabaseGraph(): Promise<DatabaseGraphResponse> {
  const response = await fetch(`${API_BASE}/api/database/graph`);

  if (!response.ok) {
    throw new Error(await response.text());
  }

  return response.json();
}

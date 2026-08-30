import {
  Folder,
  FileItem,
  IndexingStatus,
  EventItem,
  JobItem,
  HealthResponse,
  ActionResponse,
  IntegrityMode,
  ChunkListResponse,
  DocumentIntelligenceStats,
} from "../types";

const BACKEND_BASE_URL = "http://127.0.0.1:24823";

/**
 * Checks deterministic health of the local FastAPI backend.
 */
export async function checkBackendHealth(timeoutMs = 3000): Promise<HealthResponse> {
  const controller = new AbortController();
  const id = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const resp = await fetch(`${BACKEND_BASE_URL}/health`, {
      method: "GET",
      headers: { Accept: "application/json" },
      signal: controller.signal,
    });

    if (!resp.ok) {
      throw new Error(`Health check failed with status: ${resp.status}`);
    }
    return resp.json();
  } finally {
    clearTimeout(id);
  }
}

/**
 * Folders Management API
 */
export async function fetchFolders(): Promise<Folder[]> {
  const resp = await fetch(`${BACKEND_BASE_URL}/folders`);
  if (!resp.ok) throw new Error("Failed to fetch registered folders");
  return resp.json();
}

export async function createFolder(
  path: string,
  recursive = true,
  integrity_mode: IntegrityMode = "NORMAL",
  indexing_enabled = true,
  exclude_patterns: string[] = []
): Promise<Folder> {
  const resp = await fetch(`${BACKEND_BASE_URL}/folders`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      path,
      recursive,
      integrity_mode,
      indexing_enabled,
      exclude_patterns,
    }),
  });

  if (!resp.ok) {
    const err = await resp.json().catch(() => ({ detail: "Failed to create folder" }));
    throw new Error(err.detail || "Failed to register folder");
  }
  return resp.json();
}

export async function updateFolder(
  folderId: string,
  updates: Partial<Folder>
): Promise<Folder> {
  const resp = await fetch(`${BACKEND_BASE_URL}/folders/${folderId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(updates),
  });
  if (!resp.ok) throw new Error("Failed to update folder");
  return resp.json();
}

export async function deleteFolder(folderId: string): Promise<void> {
  const resp = await fetch(`${BACKEND_BASE_URL}/folders/${folderId}`, {
    method: "DELETE",
  });
  if (!resp.ok && resp.status !== 204) throw new Error("Failed to delete folder");
}

/**
 * Files API
 */
export async function fetchFiles(
  folderId?: string,
  status?: string,
  limit = 100,
  offset = 0
): Promise<{ total: number; files: FileItem[] }> {
  const params = new URLSearchParams();
  if (folderId) params.append("folder_id", folderId);
  if (status) params.append("status", status);
  params.append("limit", limit.toString());
  params.append("offset", offset.toString());

  const resp = await fetch(`${BACKEND_BASE_URL}/files?${params.toString()}`);
  if (!resp.ok) throw new Error("Failed to fetch tracked files");
  return resp.json();
}

/**
 * Phase 2: Document Intelligence API
 */
export async function fetchFileChunks(fileId: string): Promise<ChunkListResponse> {
  const resp = await fetch(`${BACKEND_BASE_URL}/files/${fileId}/chunks`);
  if (!resp.ok) throw new Error(`Failed to fetch chunks for file ${fileId}`);
  return resp.json();
}

export async function fetchDocumentIntelligenceStats(): Promise<DocumentIntelligenceStats> {
  const resp = await fetch(`${BACKEND_BASE_URL}/intelligence/status`);
  if (!resp.ok) throw new Error("Failed to fetch document intelligence status");
  return resp.json();
}

/**
 * Indexing & Control API
 */
export async function fetchIndexingStatus(): Promise<IndexingStatus> {
  const resp = await fetch(`${BACKEND_BASE_URL}/indexing/status`);
  if (!resp.ok) throw new Error("Failed to fetch indexing status");
  return resp.json();
}

export async function controlIndexing(
  action: "START" | "PAUSE" | "RESUME" | "STOP" | "RESCAN",
  folderId?: string
): Promise<IndexingStatus> {
  const resp = await fetch(`${BACKEND_BASE_URL}/indexing/control`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action, folder_id: folderId }),
  });
  if (!resp.ok) throw new Error(`Failed to execute ${action} indexing`);
  const data = await resp.json();
  return data.status;
}

/**
 * Events & Jobs API
 */
export async function fetchEvents(folderId?: string, limit = 50): Promise<EventItem[]> {
  const params = new URLSearchParams();
  if (folderId) params.append("folder_id", folderId);
  params.append("limit", limit.toString());

  const resp = await fetch(`${BACKEND_BASE_URL}/events?${params.toString()}`);
  if (!resp.ok) return [];
  const data = await resp.json();
  return data.events || [];
}

export async function fetchJobs(status?: string, limit = 50): Promise<JobItem[]> {
  const params = new URLSearchParams();
  if (status) params.append("status", status);
  params.append("limit", limit.toString());

  const resp = await fetch(`${BACKEND_BASE_URL}/jobs?${params.toString()}`);
  if (!resp.ok) return [];
  const data = await resp.json();
  return data.jobs || [];
}

/**
 * Safe Filesystem Actions API
 */
export async function executeSafeAction(
  action: "OPEN_FILE" | "OPEN_FOLDER" | "COPY_PATH",
  targetPath: string
): Promise<ActionResponse> {
  const resp = await fetch(`${BACKEND_BASE_URL}/fs/action`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action, target_path: targetPath }),
  });

  if (!resp.ok) {
    const err = await resp.json().catch(() => ({ detail: "Action execution failed" }));
    throw new Error(err.detail || "Action failed");
  }
  return resp.json();
}

/**
 * Phase 3: Local Retrieval Search API
 */
export async function searchEvidence(
  request: import("../types").SearchRequest
): Promise<import("../types").SearchResponse> {
  const resp = await fetch(`${BACKEND_BASE_URL}/search`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });

  if (!resp.ok) {
    const err = await resp.json().catch(() => ({ detail: "Search request failed" }));
    throw new Error(err.detail || "Search failed");
  }
  return resp.json();
}


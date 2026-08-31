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
  ChunkItem,
  DocumentIntelligenceStats,
  SearchRequest,
  SearchResponse,
  SearchResultItem,
} from "../types";

const BACKEND_BASE_URL = "http://127.0.0.1:24823";

/**
 * Helper to perform HTTP JSON requests with clear error attribution.
 */
async function requestJson<T>(
  url: string,
  options?: RequestInit,
  operationName = "API request"
): Promise<T> {
  let resp: Response;
  try {
    resp = await fetch(url, options);
  } catch (netErr: unknown) {
    const isAbort =
      netErr instanceof DOMException && netErr.name === "AbortError";
    const netMsg = isAbort
      ? "Request timed out"
      : netErr instanceof Error
      ? netErr.message
      : String(netErr);
    console.error(`[API Network Error] ${operationName} (${url}):`, netErr);
    throw new Error(`Network failure during ${operationName}: ${netMsg}`);
  }

  if (!resp.ok) {
    let detail = `HTTP ${resp.status} ${resp.statusText}`;
    try {
      const errBody = await resp.json();
      if (errBody?.detail) {
        detail =
          typeof errBody.detail === "string"
            ? errBody.detail
            : JSON.stringify(errBody.detail);
      } else if (errBody?.message) {
        detail = errBody.message;
      }
    } catch {
      // Non-JSON response body
    }
    console.error(
      `[API HTTP Error] ${operationName} (${url}) -> ${resp.status}:`,
      detail
    );
    throw new Error(`${operationName} failed: ${detail}`);
  }

  // Handle HTTP 204 No Content or zero-length responses
  if (resp.status === 204) {
    return undefined as T;
  }

  const contentLength = resp.headers.get("content-length");
  if (contentLength === "0") {
    return undefined as T;
  }

  try {
    const text = await resp.text();
    if (!text || !text.trim()) {
      return undefined as T;
    }
    const data = JSON.parse(text);
    return data as T;
  } catch (parseErr: unknown) {
    console.error(`[API Parse Error] ${operationName} (${url}):`, parseErr);
    throw new Error(`Failed to parse response JSON from ${operationName}`);
  }
}

/**
 * Checks deterministic health of the local FastAPI backend.
 */
export async function checkBackendHealth(timeoutMs = 3000): Promise<HealthResponse> {
  const controller = new AbortController();
  const id = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const data = await requestJson<any>(
      `${BACKEND_BASE_URL}/health`,
      {
        method: "GET",
        headers: { Accept: "application/json" },
        signal: controller.signal,
      },
      "Health check"
    );

    return {
      status: data?.status || "healthy",
      service: data?.service || "FileMind Backend",
      version: data?.version || "0.1.0",
      port: data?.port || 24823,
    };
  } finally {
    clearTimeout(id);
  }
}

/**
 * Folders Management API
 */
export async function fetchFolders(): Promise<Folder[]> {
  const data = await requestJson<any>(
    `${BACKEND_BASE_URL}/folders`,
    { method: "GET" },
    "Fetch registered folders"
  );

  const folders: Folder[] = Array.isArray(data)
    ? data
    : Array.isArray(data?.value)
    ? data.value
    : Array.isArray(data?.folders)
    ? data.folders
    : Array.isArray(data?.data)
    ? data.data
    : [];

  return folders;
}

export async function createFolder(
  path: string,
  recursive = true,
  integrity_mode: IntegrityMode = "NORMAL",
  indexing_enabled = true,
  exclude_patterns: string[] = []
): Promise<Folder> {
  const data = await requestJson<any>(
    `${BACKEND_BASE_URL}/folders`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        path,
        recursive,
        integrity_mode,
        indexing_enabled,
        exclude_patterns,
      }),
    },
    "Register folder"
  );

  return data?.folder || data?.value || data;
}

export async function updateFolder(
  folderId: string,
  updates: Partial<Folder>
): Promise<Folder> {
  const data = await requestJson<any>(
    `${BACKEND_BASE_URL}/folders/${folderId}`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(updates),
    },
    "Update folder"
  );

  return data?.folder || data?.value || data;
}

export async function deleteFolder(folderId: string): Promise<void> {
  await requestJson<void>(
    `${BACKEND_BASE_URL}/folders/${folderId}`,
    { method: "DELETE" },
    "Delete folder"
  );
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

  const data = await requestJson<any>(
    `${BACKEND_BASE_URL}/files?${params.toString()}`,
    { method: "GET" },
    "Fetch tracked files"
  );

  let fileList: FileItem[] = [];
  let totalCount = 0;

  if (Array.isArray(data)) {
    fileList = data;
    totalCount = data.length;
  } else if (Array.isArray(data?.files)) {
    fileList = data.files;
    totalCount = typeof data.total === "number" ? data.total : data.files.length;
  } else if (Array.isArray(data?.value)) {
    fileList = data.value;
    totalCount =
      typeof data.Count === "number"
        ? data.Count
        : typeof data.total === "number"
        ? data.total
        : data.value.length;
  } else if (Array.isArray(data?.items)) {
    fileList = data.items;
    totalCount = typeof data.total === "number" ? data.total : data.items.length;
  }

  return {
    total: totalCount,
    files: fileList,
  };
}

/**
 * Phase 2: Document Intelligence API
 */
export async function fetchFileChunks(fileId: string): Promise<ChunkListResponse> {
  const data = await requestJson<any>(
    `${BACKEND_BASE_URL}/files/${fileId}/chunks`,
    { method: "GET" },
    `Fetch file chunks (${fileId})`
  );

  const chunks: ChunkItem[] = Array.isArray(data)
    ? data
    : Array.isArray(data?.chunks)
    ? data.chunks
    : Array.isArray(data?.value)
    ? data.value
    : [];

  return {
    total: typeof data?.total === "number" ? data.total : chunks.length,
    file_id: data?.file_id || fileId,
    filename: data?.filename || "",
    source_path: data?.source_path || "",
    chunks,
  };
}

export async function fetchDocumentIntelligenceStats(): Promise<DocumentIntelligenceStats> {
  const data = await requestJson<any>(
    `${BACKEND_BASE_URL}/intelligence/status`,
    { method: "GET" },
    "Fetch intelligence stats"
  );

  return {
    total_chunks: data?.total_chunks ?? 0,
    files_with_chunks: data?.files_with_chunks ?? 0,
    indexed_files: data?.indexed_files ?? 0,
    queued_files: data?.queued_files ?? 0,
    failed_files: data?.failed_files ?? 0,
    skipped_files: data?.skipped_files ?? 0,
  };
}

/**
 * Indexing & Control API
 */
export async function fetchIndexingStatus(): Promise<IndexingStatus> {
  const data = await requestJson<any>(
    `${BACKEND_BASE_URL}/indexing/status`,
    { method: "GET" },
    "Fetch indexing status"
  );

  const s = data?.status || data;
  return {
    is_running: Boolean(s?.is_running),
    is_paused: Boolean(s?.is_paused),
    total_folders: s?.total_folders ?? 0,
    total_files: s?.total_files ?? 0,
    discovered: s?.discovered ?? 0,
    queued: s?.queued ?? 0,
    processing: s?.processing ?? 0,
    indexed: s?.indexed ?? 0,
    failed: s?.failed ?? 0,
    skipped: s?.skipped ?? 0,
    missing: s?.missing ?? 0,
    progress_percent: s?.progress_percent ?? 0,
    last_updated: s?.last_updated ?? Date.now() / 1000,
  };
}

export async function controlIndexing(
  action: "START" | "PAUSE" | "RESUME" | "STOP" | "RESCAN",
  folderId?: string
): Promise<IndexingStatus> {
  const data = await requestJson<any>(
    `${BACKEND_BASE_URL}/indexing/control`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action, folder_id: folderId }),
    },
    `Indexing control (${action})`
  );

  const s = data?.status || data;
  return {
    is_running: Boolean(s?.is_running),
    is_paused: Boolean(s?.is_paused),
    total_folders: s?.total_folders ?? 0,
    total_files: s?.total_files ?? 0,
    discovered: s?.discovered ?? 0,
    queued: s?.queued ?? 0,
    processing: s?.processing ?? 0,
    indexed: s?.indexed ?? 0,
    failed: s?.failed ?? 0,
    skipped: s?.skipped ?? 0,
    missing: s?.missing ?? 0,
    progress_percent: s?.progress_percent ?? 0,
    last_updated: s?.last_updated ?? Date.now() / 1000,
  };
}

/**
 * Events & Jobs API
 */
export async function fetchEvents(folderId?: string, limit = 50): Promise<EventItem[]> {
  const params = new URLSearchParams();
  if (folderId) params.append("folder_id", folderId);
  params.append("limit", limit.toString());

  const data = await requestJson<any>(
    `${BACKEND_BASE_URL}/events?${params.toString()}`,
    { method: "GET" },
    "Fetch events"
  );

  const events: EventItem[] = Array.isArray(data)
    ? data
    : Array.isArray(data?.events)
    ? data.events
    : Array.isArray(data?.value)
    ? data.value
    : [];

  return events;
}

export async function fetchJobs(status?: string, limit = 50): Promise<JobItem[]> {
  const params = new URLSearchParams();
  if (status) params.append("status", status);
  params.append("limit", limit.toString());

  const data = await requestJson<any>(
    `${BACKEND_BASE_URL}/jobs?${params.toString()}`,
    { method: "GET" },
    "Fetch jobs"
  );

  const jobs: JobItem[] = Array.isArray(data)
    ? data
    : Array.isArray(data?.jobs)
    ? data.jobs
    : Array.isArray(data?.value)
    ? data.value
    : [];

  return jobs;
}

/**
 * Safe Filesystem Actions API
 */
export async function executeSafeAction(
  action: "OPEN_FILE" | "OPEN_FOLDER" | "COPY_PATH",
  targetPath: string
): Promise<ActionResponse> {
  const data = await requestJson<any>(
    `${BACKEND_BASE_URL}/fs/action`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action, target_path: targetPath }),
    },
    `Execute filesystem action (${action})`
  );

  return {
    success: Boolean(data?.success),
    action: data?.action || action,
    target_path: data?.target_path || targetPath,
    message: data?.message || "Action executed successfully",
  };
}

/**
 * Phase 3: Local Retrieval Search API
 */
export async function searchEvidence(
  request: SearchRequest
): Promise<SearchResponse> {
  const data = await requestJson<any>(
    `${BACKEND_BASE_URL}/search`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    },
    "Search evidence"
  );

  const results: SearchResultItem[] = Array.isArray(data?.results)
    ? data.results
    : Array.isArray(data?.value)
    ? data.value
    : Array.isArray(data)
    ? data
    : [];

  return {
    query: data?.query || request.query,
    mode: data?.mode || request.mode || "hybrid",
    total_found:
      typeof data?.total_found === "number" ? data.total_found : results.length,
    latency_breakdown_ms: {
      normalization: data?.latency_breakdown_ms?.normalization ?? 0,
      lexical_search: data?.latency_breakdown_ms?.lexical_search ?? 0,
      query_embedding: data?.latency_breakdown_ms?.query_embedding ?? 0,
      dense_search: data?.latency_breakdown_ms?.dense_search ?? 0,
      rrf_fusion: data?.latency_breakdown_ms?.rrf_fusion ?? 0,
      total_request: data?.latency_breakdown_ms?.total_request ?? 0,
    },
    results,
    degraded: Boolean(data?.degraded),
    degraded_reason: data?.degraded_reason ?? null,
    retrieval_method: data?.retrieval_method ?? null,
  };
}


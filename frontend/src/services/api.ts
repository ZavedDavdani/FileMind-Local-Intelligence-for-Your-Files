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
 * Helper to ensure a response is a non-null, non-array object.
 */
function isObject(val: unknown): val is Record<string, any> {
  return typeof val === "object" && val !== null && !Array.isArray(val);
}

/**
 * Extracts an array of items from direct arrays or verified envelope formats.
 * Throws a descriptive contract error if the response shape is unexpected.
 */
function extractArrayFromEnvelope<T>(
  data: unknown,
  arrayKey: string,
  endpointLabel: string
): T[] {
  if (Array.isArray(data)) {
    return data as T[];
  }
  if (isObject(data)) {
    if (Array.isArray(data[arrayKey])) {
      return data[arrayKey] as T[];
    }
    if (Array.isArray(data.value)) {
      return data.value as T[];
    }
    if (Array.isArray(data.items)) {
      return data.items as T[];
    }
  }
  console.error(`[API Contract Error] Invalid ${endpointLabel} response shape:`, data);
  throw new Error(`Invalid ${endpointLabel} response shape`);
}

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
    const data = await requestJson<unknown>(
      `${BACKEND_BASE_URL}/health`,
      {
        method: "GET",
        headers: { Accept: "application/json" },
        signal: controller.signal,
      },
      "Health check"
    );

    if (!isObject(data)) {
      console.error("[API Contract Error] Invalid /health response shape:", data);
      throw new Error("Invalid /health response shape");
    }

    return {
      status: typeof data.status === "string" ? data.status : "healthy",
      service: typeof data.service === "string" ? data.service : "FileMind Backend",
      version: typeof data.version === "string" ? data.version : "0.1.0",
      port: typeof data.port === "number" ? data.port : 24823,
    };
  } finally {
    clearTimeout(id);
  }
}

/**
 * Folders Management API
 */
export async function fetchFolders(): Promise<Folder[]> {
  const data = await requestJson<unknown>(
    `${BACKEND_BASE_URL}/folders`,
    { method: "GET" },
    "Fetch registered folders"
  );

  return extractArrayFromEnvelope<Folder>(data, "folders", "/folders");
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

  if (!isObject(data)) {
    console.error("[API Contract Error] Invalid POST /folders response shape:", data);
    throw new Error("Invalid POST /folders response shape");
  }

  return (data?.folder || data?.value || data) as Folder;
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

  if (!isObject(data)) {
    console.error(`[API Contract Error] Invalid PATCH /folders/${folderId} response shape:`, data);
    throw new Error(`Invalid PATCH /folders/${folderId} response shape`);
  }

  return (data?.folder || data?.value || data) as Folder;
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

  const data = await requestJson<unknown>(
    `${BACKEND_BASE_URL}/files?${params.toString()}`,
    { method: "GET" },
    "Fetch tracked files"
  );

  if (Array.isArray(data)) {
    return { total: data.length, files: data as FileItem[] };
  }

  if (isObject(data)) {
    if (Array.isArray(data.files)) {
      return {
        total: typeof data.total === "number" ? data.total : data.files.length,
        files: data.files as FileItem[],
      };
    }
    if (Array.isArray(data.value)) {
      return {
        total:
          typeof data.Count === "number"
            ? data.Count
            : typeof data.total === "number"
            ? data.total
            : data.value.length,
        files: data.value as FileItem[],
      };
    }
    if (Array.isArray(data.items)) {
      return {
        total: typeof data.total === "number" ? data.total : data.items.length,
        files: data.items as FileItem[],
      };
    }
  }

  console.error("[API Contract Error] Invalid /files response shape:", data);
  throw new Error("Invalid /files response shape");
}

/**
 * Phase 2: Document Intelligence API
 */
export async function fetchFileChunks(fileId: string): Promise<ChunkListResponse> {
  const data = await requestJson<unknown>(
    `${BACKEND_BASE_URL}/files/${fileId}/chunks`,
    { method: "GET" },
    `Fetch file chunks (${fileId})`
  );

  if (Array.isArray(data)) {
    return {
      total: data.length,
      file_id: fileId,
      filename: "",
      source_path: "",
      chunks: data as ChunkItem[],
    };
  }

  if (isObject(data)) {
    const chunks = Array.isArray(data.chunks)
      ? (data.chunks as ChunkItem[])
      : Array.isArray(data.value)
      ? (data.value as ChunkItem[])
      : null;

    if (chunks !== null) {
      return {
        total: typeof data.total === "number" ? data.total : chunks.length,
        file_id: typeof data.file_id === "string" ? data.file_id : fileId,
        filename: typeof data.filename === "string" ? data.filename : "",
        source_path: typeof data.source_path === "string" ? data.source_path : "",
        chunks,
      };
    }
  }

  console.error(`[API Contract Error] Invalid /files/${fileId}/chunks response shape:`, data);
  throw new Error(`Invalid /files/${fileId}/chunks response shape`);
}

export async function fetchDocumentIntelligenceStats(): Promise<DocumentIntelligenceStats> {
  const data = await requestJson<unknown>(
    `${BACKEND_BASE_URL}/intelligence/status`,
    { method: "GET" },
    "Fetch intelligence stats"
  );

  if (!isObject(data)) {
    console.error("[API Contract Error] Invalid /intelligence/status response shape:", data);
    throw new Error("Invalid /intelligence/status response shape");
  }

  return {
    total_chunks: typeof data.total_chunks === "number" ? data.total_chunks : 0,
    files_with_chunks: typeof data.files_with_chunks === "number" ? data.files_with_chunks : 0,
    indexed_files: typeof data.indexed_files === "number" ? data.indexed_files : 0,
    queued_files: typeof data.queued_files === "number" ? data.queued_files : 0,
    failed_files: typeof data.failed_files === "number" ? data.failed_files : 0,
    skipped_files: typeof data.skipped_files === "number" ? data.skipped_files : 0,
  };
}

/**
 * Indexing & Control API
 */
export async function fetchIndexingStatus(): Promise<IndexingStatus> {
  const data = await requestJson<unknown>(
    `${BACKEND_BASE_URL}/indexing/status`,
    { method: "GET" },
    "Fetch indexing status"
  );

  if (!isObject(data)) {
    console.error("[API Contract Error] Invalid /indexing/status response shape:", data);
    throw new Error("Invalid /indexing/status response shape");
  }

  const s = isObject(data.status) ? data.status : data;
  return {
    is_running: Boolean(s.is_running),
    is_paused: Boolean(s.is_paused),
    total_folders: typeof s.total_folders === "number" ? s.total_folders : 0,
    total_files: typeof s.total_files === "number" ? s.total_files : 0,
    discovered: typeof s.discovered === "number" ? s.discovered : 0,
    queued: typeof s.queued === "number" ? s.queued : 0,
    processing: typeof s.processing === "number" ? s.processing : 0,
    indexed: typeof s.indexed === "number" ? s.indexed : 0,
    failed: typeof s.failed === "number" ? s.failed : 0,
    skipped: typeof s.skipped === "number" ? s.skipped : 0,
    missing: typeof s.missing === "number" ? s.missing : 0,
    progress_percent: typeof s.progress_percent === "number" ? s.progress_percent : 0,
    last_updated: typeof s.last_updated === "number" ? s.last_updated : Date.now() / 1000,
  };
}

export async function controlIndexing(
  action: "START" | "PAUSE" | "RESUME" | "STOP" | "RESCAN",
  folderId?: string
): Promise<IndexingStatus> {
  const data = await requestJson<unknown>(
    `${BACKEND_BASE_URL}/indexing/control`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action, folder_id: folderId }),
    },
    `Indexing control (${action})`
  );

  if (!isObject(data)) {
    console.error(`[API Contract Error] Invalid /indexing/control (${action}) response shape:`, data);
    throw new Error(`Invalid /indexing/control response shape`);
  }

  const s = isObject(data.status) ? data.status : data;
  return {
    is_running: Boolean(s.is_running),
    is_paused: Boolean(s.is_paused),
    total_folders: typeof s.total_folders === "number" ? s.total_folders : 0,
    total_files: typeof s.total_files === "number" ? s.total_files : 0,
    discovered: typeof s.discovered === "number" ? s.discovered : 0,
    queued: typeof s.queued === "number" ? s.queued : 0,
    processing: typeof s.processing === "number" ? s.processing : 0,
    indexed: typeof s.indexed === "number" ? s.indexed : 0,
    failed: typeof s.failed === "number" ? s.failed : 0,
    skipped: typeof s.skipped === "number" ? s.skipped : 0,
    missing: typeof s.missing === "number" ? s.missing : 0,
    progress_percent: typeof s.progress_percent === "number" ? s.progress_percent : 0,
    last_updated: typeof s.last_updated === "number" ? s.last_updated : Date.now() / 1000,
  };
}

/**
 * Events & Jobs API
 */
export async function fetchEvents(folderId?: string, limit = 50): Promise<EventItem[]> {
  const params = new URLSearchParams();
  if (folderId) params.append("folder_id", folderId);
  params.append("limit", limit.toString());

  const data = await requestJson<unknown>(
    `${BACKEND_BASE_URL}/events?${params.toString()}`,
    { method: "GET" },
    "Fetch events"
  );

  return extractArrayFromEnvelope<EventItem>(data, "events", "/events");
}

export async function fetchJobs(status?: string, limit = 50): Promise<JobItem[]> {
  const params = new URLSearchParams();
  if (status) params.append("status", status);
  params.append("limit", limit.toString());

  const data = await requestJson<unknown>(
    `${BACKEND_BASE_URL}/jobs?${params.toString()}`,
    { method: "GET" },
    "Fetch jobs"
  );

  return extractArrayFromEnvelope<JobItem>(data, "jobs", "/jobs");
}

/**
 * Safe Filesystem Actions API
 */
export async function executeSafeAction(
  action: "OPEN_FILE" | "OPEN_FOLDER" | "COPY_PATH",
  targetPath: string
): Promise<ActionResponse> {
  const data = await requestJson<unknown>(
    `${BACKEND_BASE_URL}/fs/action`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action, target_path: targetPath }),
    },
    `Execute filesystem action (${action})`
  );

  if (!isObject(data)) {
    console.error("[API Contract Error] Invalid /fs/action response shape:", data);
    throw new Error("Invalid /fs/action response shape");
  }

  return {
    success: Boolean(data.success),
    action: typeof data.action === "string" ? data.action : action,
    target_path: typeof data.target_path === "string" ? data.target_path : targetPath,
    message: typeof data.message === "string" ? data.message : "Action executed successfully",
  };
}

/**
 * Phase 3: Local Retrieval Search API
 */
export async function searchEvidence(
  request: SearchRequest
): Promise<SearchResponse> {
  const data = await requestJson<unknown>(
    `${BACKEND_BASE_URL}/search`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    },
    "Search evidence"
  );

  let results: SearchResultItem[] | null = null;
  let totalFound: number | null = null;
  let latencies: any = null;
  let queryStr = request.query;
  let modeStr: "hybrid" | "bm25" | "dense" | string = request.mode || "hybrid";
  let degraded = false;
  let degradedReason: string | null = null;
  let retrievalMethod: string | null = null;

  if (Array.isArray(data)) {
    results = data as SearchResultItem[];
    totalFound = data.length;
  } else if (isObject(data)) {
    if (Array.isArray(data.results)) {
      results = data.results as SearchResultItem[];
    } else if (Array.isArray(data.value)) {
      results = data.value as SearchResultItem[];
    }

    if (results !== null) {
      totalFound = typeof data.total_found === "number" ? data.total_found : results.length;
      latencies = data.latency_breakdown_ms;
      if (typeof data.query === "string") queryStr = data.query;
      if (typeof data.mode === "string") modeStr = data.mode;
      degraded = Boolean(data.degraded);
      degradedReason = typeof data.degraded_reason === "string" ? data.degraded_reason : null;
      retrievalMethod = typeof data.retrieval_method === "string" ? data.retrieval_method : null;
    }
  }

  if (results === null) {
    console.error("[API Contract Error] Invalid /search response shape:", data);
    throw new Error("Invalid /search response shape");
  }

  return {
    query: queryStr,
    mode: modeStr,
    total_found: totalFound ?? results.length,
    latency_breakdown_ms: {
      normalization: latencies?.normalization ?? 0,
      lexical_search: latencies?.lexical_search ?? 0,
      query_embedding: latencies?.query_embedding ?? 0,
      dense_search: latencies?.dense_search ?? 0,
      rrf_fusion: latencies?.rrf_fusion ?? 0,
      total_request: latencies?.total_request ?? 0,
    },
    results,
    degraded,
    degraded_reason: degradedReason,
    retrieval_method: retrievalMethod,
  };
}

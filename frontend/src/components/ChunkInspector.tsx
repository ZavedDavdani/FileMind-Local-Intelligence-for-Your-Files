import React, { useEffect, useState } from "react";
import { ChunkItem, ChunkListResponse } from "../types";
import { fetchFileChunks } from "../services/api";

interface ChunkInspectorProps {
  fileId: string;
  filename: string;
  initialChunkId?: string;
  onClose: () => void;
}

export const ChunkInspector: React.FC<ChunkInspectorProps> = ({
  fileId,
  filename,
  initialChunkId,
  onClose,
}) => {
  const [data, setData] = useState<ChunkListResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedChunk, setSelectedChunk] = useState<ChunkItem | null>(null);

  useEffect(() => {
    if (!fileId) {
      setError("No file ID specified for chunk inspection");
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(null);
    fetchFileChunks(fileId)
      .then((res) => {
        setData(res);
        if (res.chunks && res.chunks.length > 0) {
          const matched = initialChunkId
            ? res.chunks.find((c) => c.chunk_id === initialChunkId)
            : null;
          setSelectedChunk(matched || res.chunks[0]);
        }
      })
      .catch((err) => setError(err.message || "Failed to load chunks"))
      .finally(() => setLoading(false));
  }, [fileId, initialChunkId]);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        onClose();
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [onClose]);

  return (
    <div
      onClick={onClose}
      style={{
        position: "fixed",
        top: 0,
        left: 0,
        right: 0,
        bottom: 0,
        backgroundColor: "rgba(0, 0, 0, 0.75)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: 1000,
        padding: "20px",
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label={`Chunk Inspector — ${filename}`}
        onClick={(e) => e.stopPropagation()}
        style={{
          backgroundColor: "#1e1e2e",
          color: "#cdd6f4",
          borderRadius: "12px",
          width: "90%",
          maxWidth: "1100px",
          height: "85vh",
          display: "flex",
          flexDirection: "column",
          overflow: "hidden",
          border: "1px solid #45475a",
          boxShadow: "0 20px 40px rgba(0,0,0,0.5)",
        }}
      >
        {/* Header */}
        <div
          style={{
            padding: "16px 24px",
            borderBottom: "1px solid #313244",
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            backgroundColor: "#181825",
          }}
        >
          <div>
            <h2 style={{ margin: 0, fontSize: "1.25rem", color: "#89b4fa" }}>
              Document Intelligence — Chunk Inspector
            </h2>
            <div style={{ fontSize: "0.85rem", color: "#a6adc8", marginTop: "4px" }}>
              File: <span style={{ color: "#f9e2af" }}>{filename}</span> (ID: {fileId})
            </div>
          </div>
          <button
            onClick={onClose}
            style={{
              background: "#313244",
              border: "none",
              color: "#cdd6f4",
              padding: "6px 14px",
              borderRadius: "6px",
              cursor: "pointer",
              fontWeight: 600,
            }}
          >
            ✕ Close
          </button>
        </div>

        {/* Content Body */}
        {loading ? (
          <div style={{ padding: "40px", textAlign: "center", color: "#a6adc8" }}>
            Loading chunks and provenance records...
          </div>
        ) : error ? (
          <div style={{ padding: "40px", textAlign: "center", color: "#f38ba8" }}>
            {error}
          </div>
        ) : !data || data.chunks.length === 0 ? (
          <div style={{ padding: "40px", textAlign: "center", color: "#a6adc8" }}>
            No chunks generated for this file yet.
          </div>
        ) : (
          <div style={{ display: "flex", flex: 1, overflow: "hidden" }}>
            {/* Left sidebar: Chunk list */}
            <div
              style={{
                width: "35%",
                borderRight: "1px solid #313244",
                overflowY: "auto",
                backgroundColor: "#181825",
              }}
            >
              <div
                style={{
                  padding: "12px 16px",
                  fontSize: "0.85rem",
                  color: "#a6adc8",
                  borderBottom: "1px solid #313244",
                }}
              >
                Total Chunks: <strong>{data.chunks.length}</strong>
              </div>
              {data.chunks.map((chunk, idx) => {
                const isSelected = selectedChunk?.chunk_id === chunk.chunk_id;
                return (
                  <div
                    key={chunk.chunk_id}
                    onClick={() => setSelectedChunk(chunk)}
                    style={{
                      padding: "12px 16px",
                      borderBottom: "1px solid #313244",
                      cursor: "pointer",
                      backgroundColor: isSelected ? "#313244" : "transparent",
                      transition: "background 0.15s",
                    }}
                  >
                    <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "4px" }}>
                      <span style={{ fontWeight: 600, color: isSelected ? "#89b4fa" : "#cdd6f4" }}>
                        #{idx + 1} {chunk.chunk_id}
                      </span>
                      <span
                        style={{
                          fontSize: "0.75rem",
                          padding: "2px 6px",
                          borderRadius: "4px",
                          backgroundColor: chunk.content_type === "table" ? "#a6e3a1" : chunk.content_type === "code" ? "#fab387" : "#89dceb",
                          color: "#11111b",
                          fontWeight: 700,
                        }}
                      >
                        {chunk.content_type.toUpperCase()}
                      </span>
                    </div>
                    <div style={{ fontSize: "0.8rem", color: "#bac2de", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                      {chunk.h1_parent ? `H1: ${chunk.h1_parent}` : chunk.section || "General"}
                    </div>
                    <div style={{ fontSize: "0.75rem", color: "#6c7086", marginTop: "4px" }}>
                      {chunk.page ? `Page ${chunk.page} • ` : ""}
                      {chunk.line_start ? `Lines ${chunk.line_start}-${chunk.line_end} • ` : ""}
                      ~{chunk.token_count} tokens
                    </div>
                  </div>
                );
              })}
            </div>

            {/* Right pane: Chunk detail and provenance */}
            <div style={{ flex: 1, padding: "20px", overflowY: "auto" }}>
              {selectedChunk && (
                <div>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "16px" }}>
                    <h3 style={{ margin: 0, color: "#89b4fa" }}>
                      Chunk Details: {selectedChunk.chunk_id}
                    </h3>
                    <span style={{ fontSize: "0.8rem", color: "#a6adc8" }}>
                      Index: {selectedChunk.chunk_index} | Chunker: {selectedChunk.chunker_version}
                    </span>
                  </div>

                  {/* Provenance Metadata Badges */}
                  <div
                    style={{
                      display: "grid",
                      gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))",
                      gap: "10px",
                      marginBottom: "20px",
                      backgroundColor: "#181825",
                      padding: "12px",
                      borderRadius: "8px",
                      border: "1px solid #313244",
                    }}
                  >
                    <div>
                      <span style={{ fontSize: "0.75rem", color: "#6c7086" }}>H1 Parent:</span>
                      <div style={{ fontSize: "0.85rem", color: "#f9e2af" }}>{selectedChunk.h1_parent || "None"}</div>
                    </div>
                    <div>
                      <span style={{ fontSize: "0.75rem", color: "#6c7086" }}>H2 Parent:</span>
                      <div style={{ fontSize: "0.85rem", color: "#f9e2af" }}>{selectedChunk.h2_parent || "None"}</div>
                    </div>
                    <div>
                      <span style={{ fontSize: "0.75rem", color: "#6c7086" }}>Section:</span>
                      <div style={{ fontSize: "0.85rem", color: "#cdd6f4" }}>{selectedChunk.section || "General"}</div>
                    </div>
                    <div>
                      <span style={{ fontSize: "0.75rem", color: "#6c7086" }}>Page / Span:</span>
                      <div style={{ fontSize: "0.85rem", color: "#cdd6f4" }}>
                        {selectedChunk.page ? `Page ${selectedChunk.page}` : "N/A"}
                        {selectedChunk.line_start ? ` (L${selectedChunk.line_start}-L${selectedChunk.line_end})` : ""}
                      </div>
                    </div>
                    <div>
                      <span style={{ fontSize: "0.75rem", color: "#6c7086" }}>Content Hash (SHA-256):</span>
                      <div style={{ fontSize: "0.75rem", color: "#a6e3a1", fontFamily: "monospace" }}>
                        {selectedChunk.content_hash.slice(0, 16)}...
                      </div>
                    </div>
                    <div>
                      <span style={{ fontSize: "0.75rem", color: "#6c7086" }}>Parser:</span>
                      <div style={{ fontSize: "0.85rem", color: "#cdd6f4" }}>
                        {selectedChunk.parser_name} v{selectedChunk.parser_version}
                      </div>
                    </div>
                  </div>

                  {/* Content Preview */}
                  <h4 style={{ margin: "0 0 8px 0", color: "#cdd6f4" }}>Chunk Content</h4>
                  <pre
                    style={{
                      backgroundColor: "#11111b",
                      padding: "14px",
                      borderRadius: "8px",
                      border: "1px solid #313244",
                      color: "#cdd6f4",
                      fontFamily: "monospace",
                      fontSize: "0.85rem",
                      whiteSpace: "pre-wrap",
                      wordBreak: "break-word",
                      maxHeight: "220px",
                      overflowY: "auto",
                      marginBottom: "20px",
                    }}
                  >
                    {selectedChunk.content}
                  </pre>

                  {/* Raw JSON Provenance Object */}
                  <h4 style={{ margin: "0 0 8px 0", color: "#cdd6f4" }}>Raw Provenance Record (JSON)</h4>
                  <pre
                    style={{
                      backgroundColor: "#11111b",
                      padding: "14px",
                      borderRadius: "8px",
                      border: "1px solid #313244",
                      color: "#89b4fa",
                      fontFamily: "monospace",
                      fontSize: "0.75rem",
                      whiteSpace: "pre-wrap",
                      maxHeight: "150px",
                      overflowY: "auto",
                    }}
                  >
                    {JSON.stringify(selectedChunk, null, 2)}
                  </pre>
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

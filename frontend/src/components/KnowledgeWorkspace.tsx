import React, { useState, useEffect, useCallback } from "react";
import {
  Layers,
  GitCompare,
  Sparkles,
  FileText,
  RotateCw,
  ExternalLink,
  CheckSquare,
  Square,
  Search,
  BookOpen,
} from "lucide-react";
import {
  fetchKnowledgeOverview,
  compareFiles,
  synthesizeFiles,
  fetchFiles,
} from "../services/api";
import {
  KnowledgeOverviewResponse,
  FileComparisonResponse,
  FileSynthesisResponse,
  FileItem,
} from "../types";

interface KnowledgeWorkspaceProps {
  onInspectChunk: (fileId: string, filename: string, chunkId: string) => void;
  onOpenKnowledge: (fileId: string, filename: string) => void;
  onNotify: (msg: string) => void;
}

type KnowledgeTab = "OVERVIEW" | "COMPARE" | "SYNTHESIZE";

export const KnowledgeWorkspace: React.FC<KnowledgeWorkspaceProps> = ({
  onInspectChunk,
  onOpenKnowledge,
  onNotify,
}) => {
  const [activeTab, setActiveTab] = useState<KnowledgeTab>("OVERVIEW");
  const [overview, setOverview] = useState<KnowledgeOverviewResponse | null>(null);
  const [allFiles, setAllFiles] = useState<FileItem[]>([]);
  const [isLoadingOverview, setIsLoadingOverview] = useState(false);

  // Compare Tab State
  const [selectedCompareIds, setSelectedCompareIds] = useState<string[]>([]);
  const [focusAreasText, setFocusAreasText] = useState("");
  const [isComparing, setIsComparing] = useState(false);
  const [comparisonResult, setComparisonResult] = useState<FileComparisonResponse | null>(null);
  const [fileFilterCompare, setFileFilterCompare] = useState("");

  // Synthesize Tab State
  const [selectedSynthIds, setSelectedSynthIds] = useState<string[]>([]);
  const [synthTopic, setSynthTopic] = useState("");
  const [isSynthesizing, setIsSynthesizing] = useState(false);
  const [synthesisResult, setSynthesisResult] = useState<FileSynthesisResponse | null>(null);
  const [fileFilterSynth, setFileFilterSynth] = useState("");

  const loadData = useCallback(async () => {
    setIsLoadingOverview(true);
    try {
      const [ovData, filesData] = await Promise.all([
        fetchKnowledgeOverview(),
        fetchFiles(undefined, "INDEXED", 300),
      ]);
      setOverview(ovData);
      setAllFiles(filesData.files);
    } catch (err: any) {
      console.error("Failed to load knowledge data", err);
      onNotify("Failed to load knowledge overview");
    } finally {
      setIsLoadingOverview(false);
    }
  }, [onNotify]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  // Comparison handlers
  const toggleCompareFile = (id: string) => {
    if (selectedCompareIds.includes(id)) {
      setSelectedCompareIds(selectedCompareIds.filter((x) => x !== id));
    } else {
      if (selectedCompareIds.length >= 5) {
        onNotify("Maximum 5 files can be compared simultaneously");
        return;
      }
      setSelectedCompareIds([...selectedCompareIds, id]);
    }
  };

  const handleRunComparison = async () => {
    if (selectedCompareIds.length < 2) {
      onNotify("Please select at least 2 files to compare");
      return;
    }
    setIsComparing(true);
    try {
      const focusAreas = focusAreasText
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean);
      const res = await compareFiles(selectedCompareIds, focusAreas);
      setComparisonResult(res);
      onNotify("Comparison completed");
    } catch (err: any) {
      onNotify(`Comparison failed: ${err.message}`);
    } finally {
      setIsComparing(false);
    }
  };

  // Synthesis handlers
  const toggleSynthFile = (id: string) => {
    if (selectedSynthIds.includes(id)) {
      setSelectedSynthIds(selectedSynthIds.filter((x) => x !== id));
    } else {
      if (selectedSynthIds.length >= 10) {
        onNotify("Maximum 10 files can be synthesized simultaneously");
        return;
      }
      setSelectedSynthIds([...selectedSynthIds, id]);
    }
  };

  const handleRunSynthesis = async () => {
    if (selectedSynthIds.length < 1) {
      onNotify("Please select at least 1 file to synthesize");
      return;
    }
    setIsSynthesizing(true);
    try {
      const res = await synthesizeFiles(selectedSynthIds, synthTopic.trim());
      setSynthesisResult(res);
      onNotify("Synthesis completed");
    } catch (err: any) {
      onNotify(`Synthesis failed: ${err.message}`);
    } finally {
      setIsSynthesizing(false);
    }
  };

  const filteredCompareFiles = allFiles.filter((f) =>
    f.filename.toLowerCase().includes(fileFilterCompare.toLowerCase())
  );

  const filteredSynthFiles = allFiles.filter((f) =>
    f.filename.toLowerCase().includes(fileFilterSynth.toLowerCase())
  );

  return (
    <div className="flex-1 flex flex-col h-full min-h-0 bg-dark-900 text-slate-100 rounded-xl border border-slate-800 overflow-hidden">
      {/* Top Header & Tab Navigation */}
      <div className="px-5 py-3.5 bg-dark-850 border-b border-slate-800 flex items-center justify-between shrink-0">
        <div className="flex items-center gap-3">
          <div className="p-2 bg-purple-900/40 border border-purple-500/30 rounded-lg text-purple-400">
            <Sparkles className="w-5 h-5" />
          </div>
          <div>
            <h2 className="text-sm font-semibold text-slate-100">Knowledge & Synthesis</h2>
            <p className="text-[11px] text-slate-400">
              Cross-file intelligence, topic clusters, and comparative synthesis
            </p>
          </div>
        </div>

        {/* Workspace Tab Switcher */}
        <div className="flex items-center bg-dark-800 rounded-lg p-1 border border-slate-700/60 text-xs">
          <button
            onClick={() => setActiveTab("OVERVIEW")}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md transition ${
              activeTab === "OVERVIEW"
                ? "bg-purple-600 text-white font-medium shadow"
                : "text-slate-400 hover:text-slate-200"
            }`}
          >
            <BookOpen className="w-3.5 h-3.5" />
            <span>Corpus Overview</span>
          </button>

          <button
            onClick={() => setActiveTab("COMPARE")}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md transition ${
              activeTab === "COMPARE"
                ? "bg-purple-600 text-white font-medium shadow"
                : "text-slate-400 hover:text-slate-200"
            }`}
          >
            <GitCompare className="w-3.5 h-3.5" />
            <span>Compare Files</span>
          </button>

          <button
            onClick={() => setActiveTab("SYNTHESIZE")}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md transition ${
              activeTab === "SYNTHESIZE"
                ? "bg-purple-600 text-white font-medium shadow"
                : "text-slate-400 hover:text-slate-200"
            }`}
          >
            <Layers className="w-3.5 h-3.5" />
            <span>Multi-File Synthesis</span>
          </button>
        </div>
      </div>

      {/* Main Workspace Content Area */}
      <div className="flex-1 overflow-y-auto p-5 space-y-5">
        {/* ==================== TAB 1: OVERVIEW ==================== */}
        {activeTab === "OVERVIEW" && (
          <div className="space-y-5">
            {isLoadingOverview ? (
              <div className="flex items-center justify-center p-12 text-purple-400 gap-2">
                <RotateCw className="w-5 h-5 animate-spin" />
                <span className="text-xs">Analyzing corpus structure and topics...</span>
              </div>
            ) : overview ? (
              <>
                {/* Stats row */}
                <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                  <div className="bg-dark-800/80 border border-slate-700/60 rounded-xl p-4">
                    <span className="text-xs font-medium text-slate-400">Indexed Files</span>
                    <p className="text-2xl font-bold text-white mt-1">
                      {overview.total_indexed_files}
                    </p>
                    <span className="text-[11px] text-purple-400">Grounded local corpus</span>
                  </div>

                  <div className="bg-dark-800/80 border border-slate-700/60 rounded-xl p-4">
                    <span className="text-xs font-medium text-slate-400">Knowledge Chunks</span>
                    <p className="text-2xl font-bold text-white mt-1">
                      {overview.total_chunks}
                    </p>
                    <span className="text-[11px] text-cyan-400">Searchable units</span>
                  </div>

                  <div className="bg-dark-800/80 border border-slate-700/60 rounded-xl p-4">
                    <span className="text-xs font-medium text-slate-400">Estimated Tokens</span>
                    <p className="text-2xl font-bold text-white mt-1">
                      {overview.estimated_tokens.toLocaleString()}
                    </p>
                    <span className="text-[11px] text-emerald-400">Total semantic volume</span>
                  </div>
                </div>

                {/* Dominant Topics */}
                {overview.dominant_topics.length > 0 && (
                  <div className="bg-dark-800/60 border border-slate-700/60 rounded-xl p-4">
                    <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-300 mb-2.5">
                      Dominant Corpus Topics
                    </h3>
                    <div className="flex flex-wrap gap-2">
                      {overview.dominant_topics.map((t, idx) => (
                        <span
                          key={idx}
                          className="px-2.5 py-1 bg-purple-950/60 border border-purple-500/40 rounded-lg text-xs font-medium text-purple-200"
                        >
                          #{t}
                        </span>
                      ))}
                    </div>
                  </div>
                )}

                {/* Topic Clusters Grid */}
                {overview.clusters.length > 0 && (
                  <div>
                    <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-400 mb-3">
                      Semantic Clusters
                    </h3>
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                      {overview.clusters.map((cluster, idx) => (
                        <div
                          key={idx}
                          className="bg-dark-800/90 border border-slate-700/70 rounded-xl p-4 space-y-3"
                        >
                          <div className="flex items-center justify-between">
                            <h4 className="text-xs font-bold text-purple-300">
                              {cluster.topic}
                            </h4>
                            <span className="text-[10px] bg-dark-700 px-2 py-0.5 rounded text-slate-400">
                              {cluster.file_count} files
                            </span>
                          </div>

                          <div className="space-y-1.5">
                            {cluster.files.map((cf) => (
                              <div
                                key={cf.file_id}
                                className="flex items-center justify-between p-2 bg-dark-900/60 rounded-lg text-xs hover:bg-dark-900 transition cursor-pointer"
                                onClick={() => onOpenKnowledge(cf.file_id, cf.filename)}
                              >
                                <div className="flex items-center gap-2 truncate">
                                  <FileText className="w-3.5 h-3.5 text-slate-400 shrink-0" />
                                  <span className="truncate font-medium text-slate-200">
                                    {cf.filename}
                                  </span>
                                </div>
                                <span className="text-[10px] text-purple-400 shrink-0">
                                  Insight →
                                </span>
                              </div>
                            ))}
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Recent Document Summaries */}
                {overview.recent_insights.length > 0 && (
                  <div>
                    <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-400 mb-3">
                      Recently Generated Insights
                    </h3>
                    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
                      {overview.recent_insights.map((ins) => (
                        <div
                          key={ins.file_id}
                          onClick={() => onOpenKnowledge(ins.file_id, ins.filename)}
                          className="bg-dark-800/70 hover:bg-dark-800 border border-slate-700/60 hover:border-purple-500/50 rounded-xl p-3.5 cursor-pointer transition flex flex-col justify-between space-y-2"
                        >
                          <div>
                            <div className="flex items-center gap-2 mb-1.5">
                              <FileText className="w-3.5 h-3.5 text-purple-400 shrink-0" />
                              <span className="text-xs font-semibold text-slate-200 truncate">
                                {ins.filename}
                              </span>
                            </div>
                            <p className="text-[11px] text-slate-400 line-clamp-2 leading-relaxed">
                              {ins.summary_preview}
                            </p>
                          </div>
                          <div className="text-[10px] text-slate-500 flex justify-end">
                            Open Intelligence Sheet →
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </>
            ) : (
              <div className="p-8 text-center text-xs text-slate-400">
                No indexed files in corpus yet. Register a folder on the dashboard to begin.
              </div>
            )}
          </div>
        )}

        {/* ==================== TAB 2: COMPARE ==================== */}
        {activeTab === "COMPARE" && (
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">
            {/* Left: File Selector */}
            <div className="bg-dark-850 border border-slate-800 rounded-xl p-4 flex flex-col h-[520px]">
              <div className="flex items-center justify-between mb-2">
                <span className="text-xs font-semibold text-slate-200">
                  Select Files to Compare ({selectedCompareIds.length}/5)
                </span>
                {selectedCompareIds.length > 0 && (
                  <button
                    onClick={() => setSelectedCompareIds([])}
                    className="text-[10px] text-purple-400 hover:text-purple-300"
                  >
                    Clear All
                  </button>
                )}
              </div>

              <div className="relative mb-2">
                <Search className="w-3 h-3 absolute left-2.5 top-2.5 text-slate-500" />
                <input
                  type="text"
                  placeholder="Filter indexed files..."
                  value={fileFilterCompare}
                  onChange={(e) => setFileFilterCompare(e.target.value)}
                  className="w-full bg-dark-900 border border-slate-700 rounded-lg pl-7 pr-2 py-1.5 text-xs text-slate-200 placeholder-slate-500 focus:outline-none focus:border-purple-500"
                />
              </div>

              <div className="flex-1 overflow-y-auto space-y-1 pr-1">
                {filteredCompareFiles.length === 0 ? (
                  <div className="p-4 text-center text-xs text-slate-500">
                    No indexed files match
                  </div>
                ) : (
                  filteredCompareFiles.map((f) => {
                    const isSelected = selectedCompareIds.includes(f.file_id || "");
                    return (
                      <div
                        key={f.file_id}
                        onClick={() => f.file_id && toggleCompareFile(f.file_id)}
                        className={`flex items-center gap-2 p-2 rounded-lg text-xs cursor-pointer transition ${
                          isSelected
                            ? "bg-purple-950/60 border border-purple-500/50 text-purple-100"
                            : "bg-dark-900/40 hover:bg-dark-900 border border-transparent text-slate-300"
                        }`}
                      >
                        {isSelected ? (
                          <CheckSquare className="w-3.5 h-3.5 text-purple-400 shrink-0" />
                        ) : (
                          <Square className="w-3.5 h-3.5 text-slate-600 shrink-0" />
                        )}
                        <span className="truncate font-medium">{f.filename}</span>
                      </div>
                    );
                  })
                )}
              </div>

              <div className="mt-3 pt-3 border-t border-slate-800 space-y-2">
                <div>
                  <label className="block text-[11px] font-medium text-slate-400 mb-1">
                    Focus Dimensions (Optional, comma-separated)
                  </label>
                  <input
                    type="text"
                    placeholder="e.g., pricing, deadlines, architecture"
                    value={focusAreasText}
                    onChange={(e) => setFocusAreasText(e.target.value)}
                    className="w-full bg-dark-900 border border-slate-700 rounded-lg px-2.5 py-1.5 text-xs text-slate-200 placeholder-slate-500 focus:outline-none focus:border-purple-500"
                  />
                </div>

                <button
                  onClick={handleRunComparison}
                  disabled={selectedCompareIds.length < 2 || isComparing}
                  className="w-full py-2 bg-gradient-to-r from-purple-600 to-indigo-600 hover:from-purple-500 hover:to-indigo-500 disabled:opacity-40 disabled:cursor-not-allowed text-white text-xs font-semibold rounded-lg shadow transition flex items-center justify-center gap-2"
                >
                  {isComparing ? (
                    <>
                      <RotateCw className="w-3.5 h-3.5 animate-spin" />
                      <span>Comparing Documents...</span>
                    </>
                  ) : (
                    <>
                      <GitCompare className="w-3.5 h-3.5" />
                      <span>Compare Selected ({selectedCompareIds.length})</span>
                    </>
                  )}
                </button>
              </div>
            </div>

            {/* Right: Comparison Matrix Result */}
            <div className="lg:col-span-2 bg-dark-850 border border-slate-800 rounded-xl p-5 overflow-y-auto h-[520px]">
              {comparisonResult ? (
                <div className="space-y-5">
                  <div className="border-b border-slate-700 pb-3">
                    <h3 className="text-sm font-bold text-slate-100 flex items-center gap-2">
                      <GitCompare className="w-4 h-4 text-purple-400" />
                      Cross-File Comparative Synthesis
                    </h3>
                    <div className="flex flex-wrap gap-1.5 mt-2">
                      {comparisonResult.files.map((f) => (
                        <span
                          key={f.file_id}
                          className="px-2 py-0.5 bg-dark-800 border border-slate-700 rounded text-[11px] font-medium text-slate-300"
                        >
                          {f.filename}
                        </span>
                      ))}
                    </div>
                  </div>

                  {/* Executive Summary */}
                  <div className="bg-dark-900/80 border border-slate-700/70 rounded-xl p-4">
                    <h4 className="text-xs font-semibold uppercase tracking-wider text-purple-300 mb-1.5">
                      Executive Comparative Analysis
                    </h4>
                    <p className="text-xs text-slate-200 leading-relaxed whitespace-pre-wrap">
                      {comparisonResult.executive_summary}
                    </p>
                  </div>

                  {/* Comparison Points */}
                  {comparisonResult.comparison_points.length > 0 && (
                    <div className="space-y-3">
                      <h4 className="text-xs font-semibold uppercase tracking-wider text-slate-400">
                        Dimensional Breakdown
                      </h4>
                      {comparisonResult.comparison_points.map((pt, idx) => (
                        <div
                          key={idx}
                          className="bg-dark-900/60 border border-slate-700/60 rounded-xl p-4 space-y-2"
                        >
                          <h5 className="text-xs font-bold text-slate-100">{pt.aspect}</h5>
                          <p className="text-[11px] text-slate-300 leading-relaxed">
                            {pt.summary}
                          </p>
                        </div>
                      ))}
                    </div>
                  )}

                  {/* Grounded Citations */}
                  {comparisonResult.citations.length > 0 && (
                    <div className="pt-3 border-t border-slate-800">
                      <h4 className="text-xs font-semibold uppercase tracking-wider text-purple-400 mb-2 flex items-center gap-1.5">
                        <FileText className="w-3.5 h-3.5" />
                        <span>Supporting Evidence ({comparisonResult.citations.length})</span>
                      </h4>
                      <div className="flex flex-wrap gap-2">
                        {comparisonResult.citations.map((c, idx) => (
                          <button
                            key={c.citation_id || idx}
                            onClick={() =>
                              onInspectChunk(c.file_id, c.source_file, c.chunk_id)
                            }
                            className="inline-flex items-center gap-1 px-2.5 py-1 bg-purple-950/40 hover:bg-purple-900/60 border border-purple-500/30 rounded-lg text-xs text-purple-200 hover:text-white transition"
                          >
                            <span className="font-semibold text-purple-400">[{idx + 1}]</span>
                            <span className="truncate max-w-[140px]">{c.source_file}</span>
                            {c.page && <span>p.{c.page}</span>}
                            <ExternalLink className="w-2.5 h-2.5 opacity-60" />
                          </button>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              ) : (
                <div className="h-full flex flex-col items-center justify-center text-center p-8 text-slate-400 space-y-2">
                  <GitCompare className="w-8 h-8 text-slate-600" />
                  <p className="text-xs font-medium">No comparison run yet.</p>
                  <p className="text-[11px] text-slate-500 max-w-xs">
                    Select 2 to 5 files from the left list and click "Compare Selected" to generate an executive structural and semantic comparison.
                  </p>
                </div>
              )}
            </div>
          </div>
        )}

        {/* ==================== TAB 3: SYNTHESIZE ==================== */}
        {activeTab === "SYNTHESIZE" && (
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">
            {/* Left: File Selector */}
            <div className="bg-dark-850 border border-slate-800 rounded-xl p-4 flex flex-col h-[520px]">
              <div className="flex items-center justify-between mb-2">
                <span className="text-xs font-semibold text-slate-200">
                  Select Files ({selectedSynthIds.length}/10)
                </span>
                {selectedSynthIds.length > 0 && (
                  <button
                    onClick={() => setSelectedSynthIds([])}
                    className="text-[10px] text-purple-400 hover:text-purple-300"
                  >
                    Clear All
                  </button>
                )}
              </div>

              <div className="relative mb-2">
                <Search className="w-3 h-3 absolute left-2.5 top-2.5 text-slate-500" />
                <input
                  type="text"
                  placeholder="Filter indexed files..."
                  value={fileFilterSynth}
                  onChange={(e) => setFileFilterSynth(e.target.value)}
                  className="w-full bg-dark-900 border border-slate-700 rounded-lg pl-7 pr-2 py-1.5 text-xs text-slate-200 placeholder-slate-500 focus:outline-none focus:border-purple-500"
                />
              </div>

              <div className="flex-1 overflow-y-auto space-y-1 pr-1">
                {filteredSynthFiles.length === 0 ? (
                  <div className="p-4 text-center text-xs text-slate-500">
                    No indexed files match
                  </div>
                ) : (
                  filteredSynthFiles.map((f) => {
                    const isSelected = selectedSynthIds.includes(f.file_id || "");
                    return (
                      <div
                        key={f.file_id}
                        onClick={() => f.file_id && toggleSynthFile(f.file_id)}
                        className={`flex items-center gap-2 p-2 rounded-lg text-xs cursor-pointer transition ${
                          isSelected
                            ? "bg-purple-950/60 border border-purple-500/50 text-purple-100"
                            : "bg-dark-900/40 hover:bg-dark-900 border border-transparent text-slate-300"
                        }`}
                      >
                        {isSelected ? (
                          <CheckSquare className="w-3.5 h-3.5 text-purple-400 shrink-0" />
                        ) : (
                          <Square className="w-3.5 h-3.5 text-slate-600 shrink-0" />
                        )}
                        <span className="truncate font-medium">{f.filename}</span>
                      </div>
                    );
                  })
                )}
              </div>

              <div className="mt-3 pt-3 border-t border-slate-800 space-y-2">
                <div>
                  <label className="block text-[11px] font-medium text-slate-400 mb-1">
                    Synthesis Topic / Focus Prompt
                  </label>
                  <input
                    type="text"
                    placeholder="e.g., Key milestones and financial deliverables"
                    value={synthTopic}
                    onChange={(e) => setSynthTopic(e.target.value)}
                    className="w-full bg-dark-900 border border-slate-700 rounded-lg px-2.5 py-1.5 text-xs text-slate-200 placeholder-slate-500 focus:outline-none focus:border-purple-500"
                  />
                </div>

                <button
                  onClick={handleRunSynthesis}
                  disabled={selectedSynthIds.length < 1 || isSynthesizing}
                  className="w-full py-2 bg-gradient-to-r from-purple-600 to-indigo-600 hover:from-purple-500 hover:to-indigo-500 disabled:opacity-40 disabled:cursor-not-allowed text-white text-xs font-semibold rounded-lg shadow transition flex items-center justify-center gap-2"
                >
                  {isSynthesizing ? (
                    <>
                      <RotateCw className="w-3.5 h-3.5 animate-spin" />
                      <span>Synthesizing Files...</span>
                    </>
                  ) : (
                    <>
                      <Layers className="w-3.5 h-3.5" />
                      <span>Synthesize ({selectedSynthIds.length} files)</span>
                    </>
                  )}
                </button>
              </div>
            </div>

            {/* Right: Synthesis Result */}
            <div className="lg:col-span-2 bg-dark-850 border border-slate-800 rounded-xl p-5 overflow-y-auto h-[520px]">
              {synthesisResult ? (
                <div className="space-y-5">
                  <div className="border-b border-slate-700 pb-3">
                    <h3 className="text-sm font-bold text-slate-100 flex items-center gap-2">
                      <Layers className="w-4 h-4 text-purple-400" />
                      Cross-Document Synthesis
                    </h3>
                    <p className="text-xs text-purple-300 mt-1 font-medium">
                      Topic: {synthesisResult.topic}
                    </p>
                  </div>

                  {/* Synthesized Summary */}
                  <div className="bg-dark-900/80 border border-slate-700/70 rounded-xl p-4">
                    <h4 className="text-xs font-semibold uppercase tracking-wider text-purple-300 mb-1.5">
                      Synthesized Overview
                    </h4>
                    <p className="text-xs text-slate-200 leading-relaxed whitespace-pre-wrap">
                      {synthesisResult.synthesized_summary}
                    </p>
                  </div>

                  {/* Common Themes */}
                  {synthesisResult.common_themes.length > 0 && (
                    <div className="bg-dark-900/60 border border-slate-700/60 rounded-xl p-4 space-y-2">
                      <h4 className="text-xs font-semibold uppercase tracking-wider text-slate-400">
                        Common Themes
                      </h4>
                      <ul className="list-disc list-inside space-y-1 text-xs text-slate-300">
                        {synthesisResult.common_themes.map((theme, idx) => (
                          <li key={idx}>{theme}</li>
                        ))}
                      </ul>
                    </div>
                  )}

                  {/* Key Insights */}
                  {synthesisResult.key_insights.length > 0 && (
                    <div className="bg-dark-900/60 border border-slate-700/60 rounded-xl p-4 space-y-2">
                      <h4 className="text-xs font-semibold uppercase tracking-wider text-slate-400">
                        Key Strategic Insights
                      </h4>
                      <ul className="list-disc list-inside space-y-1 text-xs text-slate-300">
                        {synthesisResult.key_insights.map((insight, idx) => (
                          <li key={idx}>{insight}</li>
                        ))}
                      </ul>
                    </div>
                  )}

                  {/* Citations */}
                  {synthesisResult.citations.length > 0 && (
                    <div className="pt-3 border-t border-slate-800">
                      <h4 className="text-xs font-semibold uppercase tracking-wider text-purple-400 mb-2 flex items-center gap-1.5">
                        <FileText className="w-3.5 h-3.5" />
                        <span>Grounded Provenance Evidence ({synthesisResult.citations.length})</span>
                      </h4>
                      <div className="flex flex-wrap gap-2">
                        {synthesisResult.citations.map((c, idx) => (
                          <button
                            key={c.citation_id || idx}
                            onClick={() =>
                              onInspectChunk(c.file_id, c.source_file, c.chunk_id)
                            }
                            className="inline-flex items-center gap-1 px-2.5 py-1 bg-purple-950/40 hover:bg-purple-900/60 border border-purple-500/30 rounded-lg text-xs text-purple-200 hover:text-white transition"
                          >
                            <span className="font-semibold text-purple-400">[{idx + 1}]</span>
                            <span className="truncate max-w-[140px]">{c.source_file}</span>
                            {c.page && <span>p.{c.page}</span>}
                            <ExternalLink className="w-2.5 h-2.5 opacity-60" />
                          </button>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              ) : (
                <div className="h-full flex flex-col items-center justify-center text-center p-8 text-slate-400 space-y-2">
                  <Layers className="w-8 h-8 text-slate-600" />
                  <p className="text-xs font-medium">No synthesis run yet.</p>
                  <p className="text-[11px] text-slate-500 max-w-xs">
                    Select files on the left and provide an optional topic prompt to synthesize cross-document insights.
                  </p>
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

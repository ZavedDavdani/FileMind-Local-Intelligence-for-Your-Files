import React, { useState, useEffect, useRef, useCallback, useMemo } from "react";
import {
  MessageSquare,
  Plus,
  Trash2,
  Edit2,
  Send,
  Download,
  Folder as FolderIcon,
  FileText,
  Layers,
  Sparkles,
  AlertCircle,
  Copy,
  Check,
  RotateCw,
  Search,
  ExternalLink,
  ChevronDown,
} from "lucide-react";
import {
  fetchConversations,
  createConversation,
  fetchConversation,
  deleteConversation,
  updateConversationTitle,
  sendChatMessage,
  exportConversation,
  fetchFolders,
  fetchFiles,
  fetchModelStatus,
} from "../services/api";
import {
  ConversationItem,
  ConversationDetail,
  ChatMessageItem,
  ChatScope,
  Folder,
  FileItem,
  ModelStatusResponse,
} from "../types";

interface ChatWorkspaceProps {
  onInspectChunk: (fileId: string, filename: string, chunkId: string) => void;
  onNotify: (msg: string) => void;
}

export const ChatWorkspace: React.FC<ChatWorkspaceProps> = ({
  onInspectChunk,
  onNotify,
}) => {
  const [conversations, setConversations] = useState<ConversationItem[]>([]);
  const [activeConversationId, setActiveConversationId] = useState<string | null>(null);
  const [activeDetail, setActiveDetail] = useState<ConversationDetail | null>(null);
  const [folders, setFolders] = useState<Folder[]>([]);
  const [files, setFiles] = useState<FileItem[]>([]);
  const [modelStatus, setModelStatus] = useState<ModelStatusResponse | null>(null);

  const [inputMessage, setInputMessage] = useState("");
  const [isSending, setIsSending] = useState(false);
  const [editingTitleId, setEditingTitleId] = useState<string | null>(null);
  const [newTitle, setNewTitle] = useState("");
  const [searchQuery, setSearchQuery] = useState("");

  // Creation modal state
  const [isCreating, setIsCreating] = useState(false);
  const [newScopeType, setNewScopeType] = useState<ChatScope>("ALL");
  const [newScopeId, setNewScopeId] = useState<string>("");
  const [newChatTitle, setNewChatTitle] = useState("");

  // Controls
  const [quality, setQuality] = useState<"fast" | "quality">("fast");
  const [retrievalMode] = useState<"hybrid" | "bm25" | "dense">("hybrid");
  const [copiedMessageId, setCopiedMessageId] = useState<string | null>(null);
  const [isExporting, setIsExporting] = useState(false);

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const abortControllerRef = useRef<AbortController | null>(null);

  const loadConversations = useCallback(async () => {
    try {
      const list = await fetchConversations();
      setConversations(list);
      if (list.length > 0 && !activeConversationId) {
        setActiveConversationId(list[0].conversation_id);
      }
    } catch (err: any) {
      console.error("Failed to load conversations", err);
    }
  }, [activeConversationId]);

  const loadDependencies = useCallback(async () => {
    try {
      const [foldersData, filesData, modelData] = await Promise.all([
        fetchFolders(),
        fetchFiles(undefined, "INDEXED", 200),
        fetchModelStatus().catch(() => null),
      ]);
      setFolders(foldersData);
      setFiles(filesData.files);
      if (modelData) setModelStatus(modelData);
    } catch (err) {
      console.error("Failed to load dependencies", err);
    }
  }, []);

  useEffect(() => {
    loadConversations();
    loadDependencies();
  }, [loadConversations, loadDependencies]);

  useEffect(() => {
    if (!activeConversationId) {
      setActiveDetail(null);
      return;
    }
    let cancelled = false;
    fetchConversation(activeConversationId)
      .then((detail) => {
        if (!cancelled) {
          setActiveDetail(detail);
        }
      })
      .catch((err) => {
        if (!cancelled) {
          console.error("Failed to load active conversation", err);
          onNotify("Failed to load conversation messages");
        }
      });
    return () => {
      cancelled = true;
    };
  }, [activeConversationId, onNotify]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [activeDetail?.messages, isSending]);

  const handleStartCreate = () => {
    setNewChatTitle("");
    setNewScopeType("ALL");
    setNewScopeId("");
    setIsCreating(true);
  };

  const handleCreateSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      const created = await createConversation({
        title: newChatTitle.trim() || undefined,
        scope_type: newScopeType,
        scope_id: newScopeId.trim() || undefined,
      });
      setIsCreating(false);
      await loadConversations();
      setActiveConversationId(created.conversation_id);
      onNotify(`Created chat: ${created.title}`);
    } catch (err: any) {
      onNotify(`Failed to create chat: ${err.message}`);
    }
  };

  const handleDelete = async (conversationId: string, e: React.MouseEvent) => {
    e.stopPropagation();
    if (!confirm("Are you sure you want to delete this conversation?")) return;
    try {
      await deleteConversation(conversationId);
      onNotify("Conversation deleted");
      if (activeConversationId === conversationId) {
        setActiveConversationId(null);
      }
      loadConversations();
    } catch (err: any) {
      onNotify(`Failed to delete: ${err.message}`);
    }
  };

  const handleStartRename = (conv: ConversationItem, e: React.MouseEvent) => {
    e.stopPropagation();
    setEditingTitleId(conv.conversation_id);
    setNewTitle(conv.title);
  };

  const handleSaveRename = async (conversationId: string) => {
    if (!newTitle.trim()) {
      setEditingTitleId(null);
      return;
    }
    try {
      await updateConversationTitle(conversationId, newTitle.trim());
      setEditingTitleId(null);
      loadConversations();
      if (activeDetail && activeDetail.conversation_id === conversationId) {
        setActiveDetail({ ...activeDetail, title: newTitle.trim() });
      }
      onNotify("Conversation renamed");
    } catch (err: any) {
      onNotify(`Rename failed: ${err.message}`);
    }
  };

  const handleSendMessage = async (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    if (!inputMessage.trim() || isSending) return;

    let targetConvId = activeConversationId;
    if (!targetConvId) {
      try {
        const created = await createConversation({
          title: "New Conversation",
          scope_type: "ALL",
        });
        targetConvId = created.conversation_id;
        setActiveConversationId(targetConvId);
        await loadConversations();
      } catch (err: any) {
        onNotify(`Failed to create conversation: ${err.message}`);
        return;
      }
    }

    const messageText = inputMessage.trim();
    setInputMessage("");
    setIsSending(true);

    const tempUserMsg: ChatMessageItem = {
      message_id: `temp-${Date.now()}`,
      conversation_id: targetConvId,
      role: "user",
      content: messageText,
      citations: [],
      created_at: new Date().toISOString(),
    };

    setActiveDetail((prev) => {
      if (!prev) return null;
      return {
        ...prev,
        messages: [...prev.messages, tempUserMsg],
      };
    });

    const controller = new AbortController();
    abortControllerRef.current = controller;

    try {
      await sendChatMessage(
        targetConvId,
        {
          content: messageText,
          quality,
          mode: retrievalMode,
        },
        controller.signal
      );

      const updatedDetail = await fetchConversation(targetConvId);
      setActiveDetail(updatedDetail);
      loadConversations();
    } catch (err: any) {
      if (err.name === "AbortError") {
        onNotify("Message generation stopped");
      } else {
        onNotify(`Failed to get answer: ${err.message}`);
        if (targetConvId) {
          fetchConversation(targetConvId).then(setActiveDetail).catch(() => {});
        }
      }
    } finally {
      setIsSending(false);
      abortControllerRef.current = null;
      setTimeout(() => inputRef.current?.focus(), 50);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSendMessage();
    }
  };

  const handleCopy = (content: string, id: string) => {
    navigator.clipboard.writeText(content);
    setCopiedMessageId(id);
    setTimeout(() => setCopiedMessageId(null), 2000);
    onNotify("Copied to clipboard");
  };

  const handleExport = async (format: "markdown" | "json" | "text") => {
    if (!activeConversationId) return;
    setIsExporting(true);
    try {
      const exp = await exportConversation(activeConversationId, format, true);
      const blob = new Blob([exp.content], { type: exp.mime_type });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = exp.filename;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
      onNotify(`Exported conversation as ${format.toUpperCase()}`);
    } catch (err: any) {
      onNotify(`Export failed: ${err.message}`);
    } finally {
      setIsExporting(false);
    }
  };

  const filteredConversations = useMemo(
    () =>
      conversations.filter((c) =>
        c.title.toLowerCase().includes(searchQuery.toLowerCase())
      ),
    [conversations, searchQuery]
  );

  const getScopeBadge = useCallback(
    (scopeType: ChatScope, scopeId?: string | null) => {
      if (scopeType === "FOLDER") {
        const folder = folders.find((f) => f.folder_id === scopeId);
        const folderName = folder ? folder.path.split(/[/\\]/).filter(Boolean).pop() : scopeId;
        return (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-medium bg-amber-500/20 text-amber-300 border border-amber-500/30">
            <FolderIcon className="w-3 h-3" />
            Folder: {folderName || "Selected"}
          </span>
        );
      }
      if (scopeType === "FILE") {
        const file = files.find((f) => f.file_id === scopeId);
        return (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-medium bg-cyan-500/20 text-cyan-300 border border-cyan-500/30">
            <FileText className="w-3 h-3" />
            File: {file?.filename || "Selected"}
          </span>
        );
      }
      return (
        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-medium bg-purple-500/20 text-purple-300 border border-purple-500/30">
          <Layers className="w-3 h-3" />
          All Files
        </span>
      );
    },
    [folders, files]
  );

  return (
    <div className="flex-1 flex h-full min-h-0 bg-dark-900 text-slate-100 rounded-xl border border-slate-800 overflow-hidden">
      {/* Sidebar: Conversation List */}
      <div className="w-72 sm:w-80 flex flex-col bg-dark-850 border-r border-slate-800 shrink-0">
        <div className="p-3 border-b border-slate-800 space-y-2">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold uppercase tracking-wider text-slate-400 flex items-center gap-1.5">
              <MessageSquare className="w-3.5 h-3.5 text-purple-400" />
              Chat Threads
            </span>
            <button
              onClick={handleStartCreate}
              className="flex items-center gap-1 px-2.5 py-1 bg-purple-600 hover:bg-purple-500 text-white text-xs font-medium rounded-lg transition shadow-sm"
              title="New Chat with Custom Scope"
            >
              <Plus className="w-3.5 h-3.5" />
              <span>New</span>
            </button>
          </div>

          <div className="relative">
            <Search className="w-3.5 h-3.5 absolute left-2.5 top-2.5 text-slate-500" />
            <input
              type="text"
              placeholder="Filter threads..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full bg-dark-800 border border-slate-700/60 rounded-lg pl-8 pr-3 py-1.5 text-xs text-slate-200 placeholder-slate-500 focus:outline-none focus:border-purple-500"
            />
          </div>
        </div>

        {/* Conversation Items List */}
        <div className="flex-1 overflow-y-auto p-2 space-y-1">
          {filteredConversations.length === 0 ? (
            <div className="p-4 text-center text-xs text-slate-500">
              {searchQuery ? "No matching conversations" : "No conversations yet. Start a new chat!"}
            </div>
          ) : (
            filteredConversations.map((conv) => {
              const isActive = conv.conversation_id === activeConversationId;
              const isEditing = editingTitleId === conv.conversation_id;

              return (
                <div
                  key={conv.conversation_id}
                  onClick={() => setActiveConversationId(conv.conversation_id)}
                  className={`group flex flex-col p-2.5 rounded-lg cursor-pointer transition border ${
                    isActive
                      ? "bg-purple-950/40 border-purple-500/40 text-purple-100"
                      : "bg-dark-800/40 hover:bg-dark-800 border-transparent text-slate-300"
                  }`}
                >
                  <div className="flex items-center justify-between">
                    {isEditing ? (
                      <input
                        type="text"
                        value={newTitle}
                        onChange={(e) => setNewTitle(e.target.value)}
                        onBlur={() => handleSaveRename(conv.conversation_id)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter") handleSaveRename(conv.conversation_id);
                          if (e.key === "Escape") setEditingTitleId(null);
                        }}
                        autoFocus
                        onClick={(e) => e.stopPropagation()}
                        className="w-full bg-dark-900 border border-purple-500 rounded px-1.5 py-0.5 text-xs text-white"
                      />
                    ) : (
                      <span className="text-xs font-medium truncate flex-1 pr-2" title={conv.title}>
                        {conv.title}
                      </span>
                    )}

                    <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition shrink-0">
                      <button
                        onClick={(e) => handleStartRename(conv, e)}
                        className="p-1 hover:text-purple-300 text-slate-400"
                        title="Rename"
                      >
                        <Edit2 className="w-3 h-3" />
                      </button>
                      <button
                        onClick={(e) => handleDelete(conv.conversation_id, e)}
                        className="p-1 hover:text-rose-400 text-slate-400"
                        title="Delete"
                      >
                        <Trash2 className="w-3 h-3" />
                      </button>
                    </div>
                  </div>

                  <div className="flex items-center justify-between mt-1.5 text-[11px] text-slate-500">
                    <span className="truncate">{conv.scope_type}</span>
                    <span>{conv.message_count} msgs</span>
                  </div>
                </div>
              );
            })
          )}
        </div>

        {/* Model status footer */}
        <div className="p-2.5 bg-dark-900/60 border-t border-slate-800 text-[11px] text-slate-400 flex items-center justify-between">
          <div className="flex items-center gap-1.5 truncate">
            <span
              className={`w-2 h-2 rounded-full ${
                modelStatus?.is_ollama_online ? "bg-emerald-500" : "bg-amber-500"
              }`}
            />
            <span className="truncate">{modelStatus?.active_chat_model || "Ollama"}</span>
          </div>
          <span className="text-[10px] text-slate-500">100% Local</span>
        </div>
      </div>

      {/* Main Chat Pane */}
      <div className="flex-1 flex flex-col min-w-0 bg-dark-900">
        {/* Chat Header */}
        <div className="px-4 py-3 bg-dark-850 border-b border-slate-800 flex items-center justify-between shrink-0">
          <div className="flex items-center gap-3 min-w-0">
            <div className="min-w-0">
              <h2 className="text-sm font-semibold text-slate-100 truncate">
                {activeDetail?.title || "FileMind Chat"}
              </h2>
              <div className="flex items-center gap-2 mt-0.5">
                {activeDetail && getScopeBadge(activeDetail.scope_type, activeDetail.scope_id)}
                <span className="text-[11px] text-slate-400">Grounded Provenance</span>
              </div>
            </div>
          </div>

          <div className="flex items-center gap-2">
            {/* Retrieval quality */}
            <div className="flex items-center bg-dark-800 rounded-lg p-0.5 border border-slate-700/60 text-xs">
              <button
                onClick={() => setQuality("fast")}
                className={`px-2 py-1 rounded-md transition ${
                  quality === "fast"
                    ? "bg-purple-600 text-white font-medium"
                    : "text-slate-400 hover:text-slate-200"
                }`}
              >
                Fast
              </button>
              <button
                onClick={() => setQuality("quality")}
                className={`px-2 py-1 rounded-md transition ${
                  quality === "quality"
                    ? "bg-purple-600 text-white font-medium"
                    : "text-slate-400 hover:text-slate-200"
                }`}
              >
                Deep Rerank
              </button>
            </div>

            {/* Export Dropdown */}
            {activeDetail && activeDetail.messages.length > 0 && (
              <div className="relative group">
                <button
                  disabled={isExporting}
                  className="flex items-center gap-1.5 px-3 py-1.5 bg-dark-800 hover:bg-dark-700 text-slate-200 text-xs font-medium rounded-lg border border-slate-700 transition"
                  title="Export Conversation"
                >
                  <Download className="w-3.5 h-3.5 text-slate-400" />
                  <span>Export</span>
                  <ChevronDown className="w-3 h-3 text-slate-500" />
                </button>
                <div className="absolute right-0 top-full mt-1 w-36 bg-dark-800 border border-slate-700 rounded-lg shadow-xl py-1 hidden group-hover:block z-20">
                  <button
                    onClick={() => handleExport("markdown")}
                    className="w-full text-left px-3 py-1.5 text-xs text-slate-200 hover:bg-purple-600/30 hover:text-purple-200"
                  >
                    Markdown (.md)
                  </button>
                  <button
                    onClick={() => handleExport("json")}
                    className="w-full text-left px-3 py-1.5 text-xs text-slate-200 hover:bg-purple-600/30 hover:text-purple-200"
                  >
                    JSON (.json)
                  </button>
                  <button
                    onClick={() => handleExport("text")}
                    className="w-full text-left px-3 py-1.5 text-xs text-slate-200 hover:bg-purple-600/30 hover:text-purple-200"
                  >
                    Plain Text (.txt)
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>

        {/* Offline Warning Banner */}
        {modelStatus && !modelStatus.is_ollama_online && (
          <div className="bg-amber-950/40 border-b border-amber-500/30 px-4 py-2 flex items-center justify-between text-xs text-amber-200">
            <div className="flex items-center gap-2">
              <AlertCircle className="w-4 h-4 text-amber-400 shrink-0" />
              <span>
                Local Ollama is currently offline. Verified evidence retrieval is active, but response synthesis is in fallback mode.
              </span>
            </div>
            <span className="font-mono text-[11px] text-amber-400">127.0.0.1:11434</span>
          </div>
        )}

        {/* Messages Scroll Area */}
        <div className="flex-1 overflow-y-auto p-4 sm:p-6 space-y-4">
          {activeDetail?.messages.length === 0 ? (
            <div className="h-full flex flex-col items-center justify-center text-center p-8 space-y-3">
              <div className="w-12 h-12 rounded-2xl bg-purple-900/30 border border-purple-500/30 flex items-center justify-center text-purple-400">
                <Sparkles className="w-6 h-6" />
              </div>
              <h3 className="text-sm font-semibold text-slate-200">
                Start chatting with your files
              </h3>
              <p className="text-xs text-slate-400 max-w-sm">
                Ask multi-turn questions across your indexed knowledge base. Every answer is grounded in exact source chunks with verified citations.
              </p>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 pt-2 text-left max-w-md w-full">
                <button
                  onClick={() => {
                    setInputMessage("What are the key themes and findings across my documents?");
                    inputRef.current?.focus();
                  }}
                  className="p-2.5 bg-dark-800 hover:bg-dark-750 border border-slate-700/60 rounded-lg text-xs text-slate-300 hover:text-white transition"
                >
                  "What are the key themes across my documents?"
                </button>
                <button
                  onClick={() => {
                    setInputMessage("Summarize the most recent project notes and decisions.");
                    inputRef.current?.focus();
                  }}
                  className="p-2.5 bg-dark-800 hover:bg-dark-750 border border-slate-700/60 rounded-lg text-xs text-slate-300 hover:text-white transition"
                >
                  "Summarize recent project notes and decisions"
                </button>
              </div>
            </div>
          ) : (
            activeDetail?.messages.map((msg) => {
              const isUser = msg.role === "user";
              const isCopied = copiedMessageId === msg.message_id;

              return (
                <div
                  key={msg.message_id}
                  className={`flex flex-col ${isUser ? "items-end" : "items-start"}`}
                >
                  <div
                    className={`relative max-w-2xl rounded-2xl p-4 text-xs leading-relaxed shadow-sm ${
                      isUser
                        ? "bg-purple-600 text-white rounded-tr-sm"
                        : "bg-dark-800 border border-slate-700/70 text-slate-200 rounded-tl-sm"
                    }`}
                  >
                    {/* Role Header / Actions */}
                    <div className="flex items-center justify-between mb-1.5 pb-1 border-b border-white/10 text-[10px] opacity-75">
                      <span className="font-semibold uppercase tracking-wider">
                        {isUser ? "You" : `FileMind AI (${msg.model_name || "Local"})`}
                      </span>
                      <div className="flex items-center gap-2">
                        <button
                          onClick={() => handleCopy(msg.content, msg.message_id)}
                          className="hover:opacity-100 flex items-center gap-1"
                          title="Copy message"
                        >
                          {isCopied ? (
                            <Check className="w-3 h-3 text-emerald-300" />
                          ) : (
                            <Copy className="w-3 h-3" />
                          )}
                        </button>
                      </div>
                    </div>

                    {/* Message Body */}
                    <div className="whitespace-pre-wrap font-sans">{msg.content}</div>

                    {/* Grounded Citations (Assistant only) */}
                    {!isUser && msg.citations && msg.citations.length > 0 && (
                      <div className="mt-3 pt-2.5 border-t border-slate-700/80">
                        <div className="text-[10px] font-semibold uppercase tracking-wider text-purple-400 mb-1.5 flex items-center gap-1">
                          <FileText className="w-3 h-3" />
                          <span>Verified Evidence ({msg.citations.length})</span>
                        </div>
                        <div className="flex flex-wrap gap-1.5">
                          {msg.citations.map((c, idx) => (
                            <button
                              key={c.citation_id || `${c.chunk_id}-${idx}`}
                              onClick={() =>
                                onInspectChunk(c.file_id, c.source_file, c.chunk_id)
                              }
                              className="inline-flex items-center gap-1 px-2 py-1 bg-purple-950/50 hover:bg-purple-900/70 border border-purple-500/30 rounded-md text-[11px] text-purple-200 hover:text-white transition group"
                              title={`Inspect evidence in ${c.source_file}`}
                            >
                              <span className="font-semibold text-purple-400">
                                [{idx + 1}]
                              </span>
                              <span className="font-medium truncate max-w-[120px]">
                                {c.source_file}
                              </span>
                              {c.page && (
                                <span className="text-[10px] text-purple-400">
                                  p.{c.page}
                                </span>
                              )}
                              {c.sheet_name && (
                                <span className="text-[10px] text-purple-400">
                                  {c.sheet_name}
                                </span>
                              )}
                              {c.slide_number && (
                                <span className="text-[10px] text-purple-400">
                                  s.{c.slide_number}
                                </span>
                              )}
                              <ExternalLink className="w-2.5 h-2.5 opacity-50 group-hover:opacity-100" />
                            </button>
                          ))}
                        </div>
                      </div>
                    )}

                    {/* Status Badge if degraded */}
                    {msg.generation_status && msg.generation_status !== "READY" && (
                      <div className="mt-2 text-[10px] text-amber-400 flex items-center gap-1">
                        <AlertCircle className="w-3 h-3" />
                        <span>Status: {msg.generation_status}</span>
                      </div>
                    )}
                  </div>
                </div>
              );
            })
          )}

          {isSending && (
            <div className="flex items-center gap-2 text-xs text-purple-300 p-3 bg-dark-800/60 border border-purple-500/20 rounded-xl w-fit animate-pulse">
              <RotateCw className="w-3.5 h-3.5 animate-spin text-purple-400" />
              <span>Retrieving grounded evidence & synthesizing answer...</span>
              <button
                onClick={() => abortControllerRef.current?.abort()}
                className="ml-2 px-2 py-0.5 bg-rose-900/60 hover:bg-rose-800 text-rose-200 rounded text-[10px] font-semibold"
              >
                Stop
              </button>
            </div>
          )}

          <div ref={messagesEndRef} />
        </div>

        {/* Input Bar */}
        <div className="p-3 bg-dark-850 border-t border-slate-800 shrink-0">
          <form onSubmit={handleSendMessage} className="relative flex items-end gap-2">
            <textarea
              ref={inputRef}
              rows={2}
              value={inputMessage}
              onChange={(e) => setInputMessage(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Ask a question about your files... (Shift+Enter for newline, Enter to send)"
              className="flex-1 bg-dark-900 border border-slate-700/80 rounded-xl p-3 text-xs text-slate-100 placeholder-slate-500 focus:outline-none focus:border-purple-500 resize-none font-sans"
              disabled={isSending}
            />

            <button
              type="submit"
              disabled={!inputMessage.trim() || isSending}
              className="px-4 py-3 bg-gradient-to-r from-purple-600 to-indigo-600 hover:from-purple-500 hover:to-indigo-500 disabled:opacity-40 disabled:cursor-not-allowed text-white text-xs font-semibold rounded-xl shadow transition flex items-center gap-1.5 h-full"
            >
              <Send className="w-4 h-4" />
              <span className="hidden sm:inline">Send</span>
            </button>
          </form>
        </div>
      </div>

      {/* Create Conversation Scope Modal */}
      {isCreating && (
        <div className="fixed inset-0 bg-black/60 backdrop-blur-sm z-50 flex items-center justify-center p-4">
          <div className="bg-dark-800 border border-slate-700 rounded-xl w-full max-w-md p-5 shadow-2xl space-y-4">
            <div className="flex items-center justify-between border-b border-slate-700 pb-3">
              <h3 className="text-sm font-semibold text-slate-100 flex items-center gap-2">
                <Sparkles className="w-4 h-4 text-purple-400" />
                Create New Chat Thread
              </h3>
              <button
                onClick={() => setIsCreating(false)}
                className="text-slate-400 hover:text-white text-xs"
              >
                ✕
              </button>
            </div>

            <form onSubmit={handleCreateSubmit} className="space-y-4">
              <div>
                <label className="block text-xs font-medium text-slate-300 mb-1">
                  Thread Title (Optional)
                </label>
                <input
                  type="text"
                  placeholder="e.g., Financial Q3 Review"
                  value={newChatTitle}
                  onChange={(e) => setNewChatTitle(e.target.value)}
                  className="w-full bg-dark-900 border border-slate-700 rounded-lg px-3 py-2 text-xs text-white placeholder-slate-500 focus:outline-none focus:border-purple-500"
                />
              </div>

              <div>
                <label className="block text-xs font-medium text-slate-300 mb-1">
                  Chat Scope
                </label>
                <div className="grid grid-cols-3 gap-2">
                  <button
                    type="button"
                    onClick={() => {
                      setNewScopeType("ALL");
                      setNewScopeId("");
                    }}
                    className={`p-2.5 rounded-lg border text-xs font-medium flex flex-col items-center gap-1 transition ${
                      newScopeType === "ALL"
                        ? "bg-purple-600/30 border-purple-500 text-purple-200"
                        : "bg-dark-900 border-slate-700 text-slate-400 hover:text-white"
                    }`}
                  >
                    <Layers className="w-4 h-4" />
                    <span>All Files</span>
                  </button>

                  <button
                    type="button"
                    onClick={() => {
                      setNewScopeType("FOLDER");
                      setNewScopeId(folders[0]?.folder_id || "");
                    }}
                    className={`p-2.5 rounded-lg border text-xs font-medium flex flex-col items-center gap-1 transition ${
                      newScopeType === "FOLDER"
                        ? "bg-purple-600/30 border-purple-500 text-purple-200"
                        : "bg-dark-900 border-slate-700 text-slate-400 hover:text-white"
                    }`}
                  >
                    <FolderIcon className="w-4 h-4" />
                    <span>Folder</span>
                  </button>

                  <button
                    type="button"
                    onClick={() => {
                      setNewScopeType("FILE");
                      setNewScopeId(files[0]?.file_id || "");
                    }}
                    className={`p-2.5 rounded-lg border text-xs font-medium flex flex-col items-center gap-1 transition ${
                      newScopeType === "FILE"
                        ? "bg-purple-600/30 border-purple-500 text-purple-200"
                        : "bg-dark-900 border-slate-700 text-slate-400 hover:text-white"
                    }`}
                  >
                    <FileText className="w-4 h-4" />
                    <span>Single File</span>
                  </button>
                </div>
              </div>

              {newScopeType === "FOLDER" && (
                <div>
                  <label className="block text-xs font-medium text-slate-300 mb-1">
                    Select Target Folder
                  </label>
                  <select
                    value={newScopeId}
                    onChange={(e) => setNewScopeId(e.target.value)}
                    className="w-full bg-dark-900 border border-slate-700 rounded-lg px-3 py-2 text-xs text-white focus:outline-none focus:border-purple-500"
                  >
                    {folders.map((f) => (
                      <option key={f.folder_id} value={f.folder_id}>
                        {f.path}
                      </option>
                    ))}
                  </select>
                </div>
              )}

              {newScopeType === "FILE" && (
                <div>
                  <label className="block text-xs font-medium text-slate-300 mb-1">
                    Select Target File
                  </label>
                  <select
                    value={newScopeId}
                    onChange={(e) => setNewScopeId(e.target.value)}
                    className="w-full bg-dark-900 border border-slate-700 rounded-lg px-3 py-2 text-xs text-white focus:outline-none focus:border-purple-500"
                  >
                    {files.map((f) => (
                      <option key={f.file_id} value={f.file_id}>
                        {f.filename} ({f.extension})
                      </option>
                    ))}
                  </select>
                </div>
              )}

              <div className="flex justify-end gap-2 pt-2">
                <button
                  type="button"
                  onClick={() => setIsCreating(false)}
                  className="px-3 py-1.5 bg-dark-700 hover:bg-dark-600 text-slate-300 rounded-lg text-xs"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="px-4 py-1.5 bg-purple-600 hover:bg-purple-500 text-white font-medium rounded-lg text-xs"
                >
                  Create Thread
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
};

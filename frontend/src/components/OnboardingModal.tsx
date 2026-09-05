import React from "react";
import { Sparkles, FolderPlus, Search, MessageSquare, ShieldCheck, Check } from "lucide-react";

interface OnboardingModalProps {
  isOpen: boolean;
  onClose: () => void;
}

export const OnboardingModal: React.FC<OnboardingModalProps> = ({
  isOpen,
  onClose,
}) => {
  if (!isOpen) return null;

  const handleFinish = () => {
    localStorage.setItem("filemind_onboarding_completed", "true");
    onClose();
  };

  return (
    <div className="fixed inset-0 bg-black/70 backdrop-blur-md z-50 flex items-center justify-center p-4">
      <div className="bg-dark-850 border border-purple-500/30 rounded-2xl w-full max-w-xl p-6 shadow-2xl space-y-6 text-slate-100 animate-in fade-in zoom-in-95 duration-200">
        {/* Header */}
        <div className="text-center space-y-2">
          <div className="inline-flex p-3 bg-purple-900/40 border border-purple-500/40 rounded-2xl text-purple-400 mb-1">
            <Sparkles className="w-8 h-8" />
          </div>
          <h2 className="text-lg font-bold text-white tracking-tight">
            Welcome to FileMind
          </h2>
          <p className="text-xs text-slate-400 max-w-sm mx-auto">
            Local Intelligence for Your Files. 100% offline, privacy-first knowledge extraction & grounded chat.
          </p>
        </div>

        {/* 3 Step Guide */}
        <div className="space-y-3.5">
          <div className="flex items-start gap-3.5 p-3.5 bg-dark-900/80 border border-slate-800 rounded-xl">
            <div className="p-2 bg-purple-950/60 border border-purple-500/30 rounded-lg text-purple-400 shrink-0">
              <FolderPlus className="w-4 h-4" />
            </div>
            <div>
              <h3 className="text-xs font-semibold text-slate-200">1. Register Local Folders</h3>
              <p className="text-[11px] text-slate-400 mt-0.5 leading-relaxed">
                Add local folders containing your PDFs, Docs, Code, Spreadsheets, or Notes. FileMind automatically tracks and updates them in real-time.
              </p>
            </div>
          </div>

          <div className="flex items-start gap-3.5 p-3.5 bg-dark-900/80 border border-slate-800 rounded-xl">
            <div className="p-2 bg-cyan-950/60 border border-cyan-500/30 rounded-lg text-cyan-400 shrink-0">
              <Search className="w-4 h-4" />
            </div>
            <div>
              <h3 className="text-xs font-semibold text-slate-200">2. Instant Hybrid Search (Ctrl + K)</h3>
              <p className="text-[11px] text-slate-400 mt-0.5 leading-relaxed">
                Locate exact passages and concepts instantly with hybrid BM25 + dense vector ranking and cross-encoder precision.
              </p>
            </div>
          </div>

          <div className="flex items-start gap-3.5 p-3.5 bg-dark-900/80 border border-slate-800 rounded-xl">
            <div className="p-2 bg-emerald-950/60 border border-emerald-500/30 rounded-lg text-emerald-400 shrink-0">
              <MessageSquare className="w-4 h-4" />
            </div>
            <div>
              <h3 className="text-xs font-semibold text-slate-200">3. Grounded Chat & Synthesis (Ctrl + J)</h3>
              <p className="text-[11px] text-slate-400 mt-0.5 leading-relaxed">
                Ask questions across single files, folders, or your entire knowledge base. Every answer includes interactive provenance citations.
              </p>
            </div>
          </div>
        </div>

        {/* Privacy Note */}
        <div className="flex items-center gap-2 p-2.5 bg-emerald-950/30 border border-emerald-500/20 rounded-lg text-[11px] text-emerald-300">
          <ShieldCheck className="w-4 h-4 text-emerald-400 shrink-0" />
          <span>Zero telemetry. Zero cloud dependencies. Your files never leave your PC.</span>
        </div>

        {/* CTA Button */}
        <button
          onClick={handleFinish}
          className="w-full py-2.5 bg-gradient-to-r from-purple-600 to-indigo-600 hover:from-purple-500 hover:to-indigo-500 text-white text-xs font-bold rounded-xl shadow-lg transition flex items-center justify-center gap-2"
        >
          <Check className="w-4 h-4" />
          <span>Get Started with FileMind</span>
        </button>
      </div>
    </div>
  );
};

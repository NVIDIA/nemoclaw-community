import { useCallback, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { CheckCircle2, Loader2, Upload } from "lucide-react";

type Props = {
  onFile: (file: File) => void;
  uploading: boolean;
  currentName: string | null;
};

export function DropZone({ onFile, uploading, currentName }: Props) {
  const [dragging, setDragging] = useState(false);

  const onDrop = useCallback(
    (e: React.DragEvent<HTMLLabelElement>) => {
      e.preventDefault();
      setDragging(false);
      const file = e.dataTransfer.files?.[0];
      if (file) onFile(file);
    },
    [onFile]
  );

  return (
    <label
      onDragOver={(e) => {
        e.preventDefault();
        setDragging(true);
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={onDrop}
      className={`group flex cursor-pointer items-center gap-4 rounded-2xl border border-dashed px-5 py-4 transition-all ${
        dragging
          ? "border-nv bg-nv/5"
          : "border-white/10 bg-ink-900/50 hover:border-white/20 hover:bg-ink-800/60"
      }`}
    >
      <input
        type="file"
        accept="video/*,audio/*"
        className="hidden"
        onChange={(e) => {
          const file = e.target.files?.[0];
          if (file) onFile(file);
        }}
      />
      <div
        className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-xl transition-colors ${
          uploading
            ? "bg-nv/15"
            : currentName
            ? "bg-nv/10 text-nv"
            : "bg-ink-800 text-ink-300 group-hover:bg-ink-700"
        }`}
      >
        <AnimatePresence mode="wait">
          {uploading ? (
            <motion.div key="up" initial={{ rotate: -30, opacity: 0 }} animate={{ rotate: 0, opacity: 1 }} exit={{ opacity: 0 }}>
              <Loader2 className="h-5 w-5 animate-spin text-nv" />
            </motion.div>
          ) : currentName ? (
            <motion.div key="done" initial={{ scale: 0.7, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} exit={{ opacity: 0 }}>
              <CheckCircle2 className="h-5 w-5" />
            </motion.div>
          ) : (
            <motion.div key="up" initial={{ y: 4, opacity: 0 }} animate={{ y: 0, opacity: 1 }} exit={{ opacity: 0 }}>
              <Upload className="h-5 w-5" />
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      <div className="flex-1 min-w-0">
        <div className="text-[14px] font-medium text-white">
          {uploading
            ? "Uploading…"
            : dragging
            ? "Release to upload"
            : currentName
            ? "Replace video"
            : "Drop a video to start"}
        </div>
        <div className="mt-0.5 truncate text-[12px] text-ink-300">
          {uploading
            ? "sending to sandbox"
            : `drag an mp4, mp3, or click to choose · under ~9 MB works best`}
        </div>
      </div>

      <div className="hidden sm:block">
        <span className="rounded-full bg-ink-800 px-3 py-1 text-[11px] font-medium text-ink-300">
          MP4 · MP3 · WAV
        </span>
      </div>
    </label>
  );
}

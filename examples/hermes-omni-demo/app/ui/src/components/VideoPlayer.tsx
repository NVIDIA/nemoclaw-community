import { useEffect, useRef, useState } from "react";
import { Play, Pause, Volume2, VolumeX, AudioLines } from "lucide-react";

type Props = {
  src: string | null;
  label: string | null;
  mediaKind?: "video" | "audio";
};

export function VideoPlayer({ src, label, mediaKind = "video" }: Props) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [playing, setPlaying] = useState(true);
  const [muted, setMuted] = useState(true);
  const [time, setTime] = useState(0);
  const [duration, setDuration] = useState(0);

  useEffect(() => {
    const v = videoRef.current;
    if (!v) return;
    const onPlay = () => setPlaying(true);
    const onPause = () => setPlaying(false);
    const onTime = () => setTime(v.currentTime);
    const onMeta = () => setDuration(v.duration || 0);
    v.addEventListener("play", onPlay);
    v.addEventListener("pause", onPause);
    v.addEventListener("timeupdate", onTime);
    v.addEventListener("loadedmetadata", onMeta);
    return () => {
      v.removeEventListener("play", onPlay);
      v.removeEventListener("pause", onPause);
      v.removeEventListener("timeupdate", onTime);
      v.removeEventListener("loadedmetadata", onMeta);
    };
  }, [src]);

  const toggle = () => {
    const v = videoRef.current;
    if (!v) return;
    if (v.paused) v.play();
    else v.pause();
  };

  const toggleMute = () => {
    const v = videoRef.current;
    if (!v) return;
    v.muted = !v.muted;
    setMuted(v.muted);
  };

  const seek = (e: React.MouseEvent<HTMLDivElement>) => {
    const v = videoRef.current;
    if (!v || !duration) return;
    const rect = e.currentTarget.getBoundingClientRect();
    const x = (e.clientX - rect.left) / rect.width;
    v.currentTime = Math.max(0, Math.min(duration, x * duration));
  };

  const pct = duration > 0 ? (time / duration) * 100 : 0;

  return (
    <div className="surface overflow-hidden">
      {/* header strip */}
      <div className="flex items-center justify-between px-5 py-3">
        <div className="flex items-center gap-2">
          <span className="eyebrow">Source</span>
          <span className="text-[14px] font-medium text-white">
            {label ?? "—"}
          </span>
        </div>
        <span className="eyebrow font-mono">
          {fmt(time)} / {fmt(duration)}
        </span>
      </div>
      <div className="divider" />

      {/* video */}
      <div className="video-wrap aspect-video">
        {src && mediaKind === "audio" ? (
          <AudioVisual label={label} />
        ) : src ? (
          <video
            ref={videoRef}
            src={src}
            autoPlay
            muted={muted}
            loop
            playsInline
          />
        ) : (
          <div className="flex h-full items-center justify-center bg-black text-ink-400">
            No video loaded
          </div>
        )}

        <div className="video-shade" />

        {/* big center play/pause — shows on hover, and persistently when paused */}
        <button
          className="video-bigplay"
          data-show={!playing}
          onClick={toggle}
          aria-label={playing ? "Pause" : "Play"}
        >
          {playing ? (
            <Pause className="h-7 w-7" fill="currentColor" />
          ) : (
            <Play className="h-7 w-7 translate-x-[1px]" fill="currentColor" />
          )}
        </button>

        {/* bottom control bar */}
        <div className="video-controls">
          <button
            className="ctrl-btn"
            onClick={toggle}
            aria-label={playing ? "Pause" : "Play"}
          >
            {playing ? (
              <Pause className="h-4 w-4" fill="currentColor" />
            ) : (
              <Play className="h-4 w-4 translate-x-[1px]" fill="currentColor" />
            )}
          </button>

          <div className="scrub-track" onClick={seek}>
            <div className="scrub-fill" style={{ width: `${pct}%` }} />
            <div className="scrub-thumb" style={{ left: `${pct}%` }} />
          </div>

          <span className="font-mono text-[12px] text-white/90">
            {fmt(time)}
          </span>

          <button
            className="ctrl-btn"
            onClick={toggleMute}
            aria-label={muted ? "Unmute" : "Mute"}
          >
            {muted ? <VolumeX className="h-4 w-4" /> : <Volume2 className="h-4 w-4" />}
          </button>
        </div>
      </div>
    </div>
  );
}

function fmt(sec: number): string {
  if (!isFinite(sec) || sec < 0) return "0:00";
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

function AudioVisual({ label }: { label: string | null }) {
  // Purely decorative: 40 animated bars
  return (
    <div className="relative flex h-full w-full items-center justify-center bg-gradient-to-br from-ink-800 via-ink-900 to-black">
      <div className="flex h-24 items-end gap-1.5">
        {Array.from({ length: 40 }).map((_, i) => (
          <span
            key={i}
            className="w-1.5 rounded-full bg-nv"
            style={{
              height: `${20 + Math.abs(Math.sin(i * 0.7)) * 60 + (i % 3) * 8}%`,
              animation: `pulse-soft ${1.4 + (i % 5) * 0.22}s ease-in-out ${i * 0.035}s infinite`,
              opacity: 0.55 + (i % 4) * 0.1,
            }}
          />
        ))}
      </div>
      <div className="absolute bottom-4 flex items-center gap-2 text-[12px] text-ink-300">
        <AudioLines className="h-3.5 w-3.5 text-nv" />
        <span>audio · {label ?? "recording"}</span>
      </div>
    </div>
  );
}

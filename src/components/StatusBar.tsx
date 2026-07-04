import { useEffect, useState } from "react";
import { api } from "../api";
import type { SystemStats } from "../types";

const POLL_MS = 2000;

function Meter({ label, percent, text }: { label: string; percent: number; text: string }) {
  const p = Math.min(100, Math.max(0, percent));
  return (
    <span className="meter" title={`${label}: ${text}`}>
      <span className="meter-label">{label}</span>
      <span className="meter-track">
        <span className={`meter-fill${p >= 85 ? " meter-hot" : ""}`} style={{ width: `${p}%` }} />
      </span>
      <span className="meter-value">{text}</span>
    </span>
  );
}

export function StatusBar({ visible }: { visible: boolean }) {
  const [stats, setStats] = useState<SystemStats | null>(null);

  useEffect(() => {
    if (!visible) return;
    let alive = true;
    const tick = () => {
      api
        .systemResources()
        .then((s) => alive && setStats(s))
        .catch(() => alive && setStats(null));
    };
    tick();
    const id = setInterval(tick, POLL_MS);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, [visible]);

  if (!visible) return null;

  const gpu = stats?.gpus[0];
  return (
    <footer className="statusbar">
      {stats && (
        <span className="stat">
          <span className={`lamp ${stats.llama["9b"] ? "lamp-ok" : "lamp-ng"}`} />
          9B
          <span className={`lamp ${stats.llama["35b"] ? "lamp-ok" : "lamp-ng"}`} />
          35B
        </span>
      )}
      <span className="statusbar-meters">
        {stats === null ? (
          <span className="stat stat-dim">リソース情報を取得できません</span>
        ) : (
          <>
            <Meter label="CPU" percent={stats.cpu_percent} text={`${stats.cpu_percent.toFixed(0)}%`} />
            <Meter
              label="RAM"
              percent={stats.ram_percent}
              text={`${stats.ram_used_gb.toFixed(1)}/${stats.ram_total_gb.toFixed(0)}G`}
            />
            {gpu && (
              <>
                <Meter label="GPU" percent={gpu.gpu_percent} text={`${gpu.gpu_percent}%`} />
                <Meter
                  label="VRAM"
                  percent={gpu.vram_percent}
                  text={`${gpu.vram_used_gb.toFixed(1)}/${gpu.vram_total_gb.toFixed(0)}G`}
                />
              </>
            )}
          </>
        )}
      </span>
    </footer>
  );
}

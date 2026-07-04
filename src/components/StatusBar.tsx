import { useEffect, useState } from "react";
import { api } from "../api";
import type { SystemStats } from "../types";

const POLL_MS = 2000;

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
      {stats === null ? (
        <span className="stat stat-dim">リソース情報を取得できません</span>
      ) : (
        <>
          <span className="stat">CPU {stats.cpu_percent.toFixed(0)}%</span>
          <span className="stat">
            RAM {stats.ram_used_gb.toFixed(1)} / {stats.ram_total_gb.toFixed(0)} GB
          </span>
          {gpu && (
            <>
              <span className="stat">GPU {gpu.gpu_percent}%</span>
              <span className="stat" title={gpu.name}>
                VRAM {gpu.vram_used_gb.toFixed(1)} / {gpu.vram_total_gb.toFixed(0)} GB
              </span>
            </>
          )}
          <span className="stat stat-right">
            <span className={`lamp ${stats.llama["9b"] ? "lamp-ok" : "lamp-ng"}`} />
            9B
            <span className={`lamp ${stats.llama["35b"] ? "lamp-ok" : "lamp-ng"}`} />
            35B
          </span>
        </>
      )}
    </footer>
  );
}

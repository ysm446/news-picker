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
  const [pending35b, setPending35b] = useState(false);
  const running35b = stats?.llama["35b"] ?? false;

  // トグル操作後、実際に状態が変わったら pending を解除
  useEffect(() => {
    setPending35b(false);
  }, [running35b]);

  const toggle35b = () => {
    setPending35b(true);
    api.llama35b(running35b ? "stop" : "start").catch(() => setPending35b(false));
  };

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
          <span
            className={`lamp ${stats.llama["9b"] ? "lamp-ok" : "lamp-ng"}`}
            title="9B (常駐: 要約・採点)"
          />
          9B
          <button
            className="lamp-btn"
            onClick={toggle35b}
            disabled={pending35b}
            title={
              pending35b
                ? "切り替え中... (ロードは数十秒かかります)"
                : running35b
                  ? "35B をアンロードして VRAM を解放"
                  : "35B をロード (深堀りチャット用。オフ中は 9B が代行)"
            }
          >
            <span
              className={`lamp ${
                pending35b ? "lamp-pending" : running35b ? "lamp-ok" : "lamp-off"
              }`}
            />
            35B
          </button>
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

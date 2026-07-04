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

function shortName(name: string): string {
  return name.length > 24 ? `${name.slice(0, 22)}…` : name;
}

export function StatusBar({ visible, connected }: { visible: boolean; connected: boolean }) {
  const [stats, setStats] = useState<SystemStats | null>(null);
  const [pendingDeep, setPendingDeep] = useState(false);
  const deepRunning = stats?.llama.deep.running ?? false;

  // トグル操作後、実際に状態が変わったら pending を解除
  useEffect(() => {
    setPendingDeep(false);
  }, [deepRunning]);

  const toggleDeep = () => {
    setPendingDeep(true);
    api.llamaControl("deep", deepRunning ? "stop" : "start").catch(() => setPendingDeep(false));
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
      <span className="stat" title="バックエンドとの SSE 接続状態">
        <span className={`lamp ${connected ? "lamp-ok" : "lamp-ng"}`} />
        {connected ? "接続中" : "再接続中..."}
      </span>
      {stats && (
        <span className="stat">
          <span
            className={`lamp ${stats.llama.standard.running ? "lamp-ok" : "lamp-ng"}`}
            title={`常駐モデル: ${stats.llama.standard.name} (要約・採点・チャット代行)`}
          />
          {shortName(stats.llama.standard.name)}
          <button
            className="lamp-btn"
            onClick={toggleDeep}
            disabled={pendingDeep}
            title={
              pendingDeep
                ? "切り替え中... (ロードは数十秒かかります)"
                : deepRunning
                  ? `深堀りモデル ${stats.llama.deep.name} をアンロードして VRAM を解放`
                  : `深堀りモデル ${stats.llama.deep.name} をロード (オフ中は常駐モデルが代行)`
            }
          >
            <span
              className={`lamp ${
                pendingDeep ? "lamp-pending" : deepRunning ? "lamp-ok" : "lamp-off"
              }`}
            />
            {shortName(stats.llama.deep.name)}
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

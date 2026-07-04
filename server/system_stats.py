"""システムリソース情報 (lm-chat の /system/resources を移植)。

CPU / RAM は psutil、GPU / VRAM は pynvml。どちらも無ければ 0 を返す。
加えて llama-server (9B/35B) の死活も返す (ステータスバーのランプ用)。
"""
from __future__ import annotations

from . import config, llm

try:
    import psutil

    _PSUTIL = True
except ImportError:
    _PSUTIL = False

try:
    import pynvml as nvml

    nvml.nvmlInit()
    _NVML = True
except Exception:  # noqa: BLE001 - NVIDIA ドライバなし等
    _NVML = False


def get_resources() -> dict:
    cpu_percent = psutil.cpu_percent(interval=None) if _PSUTIL else 0
    vm = psutil.virtual_memory() if _PSUTIL else None

    gpus: list[dict] = []
    if _NVML:
        try:
            for i in range(nvml.nvmlDeviceGetCount()):
                handle = nvml.nvmlDeviceGetHandleByIndex(i)
                name = nvml.nvmlDeviceGetName(handle)
                util = nvml.nvmlDeviceGetUtilizationRates(handle)
                mem = nvml.nvmlDeviceGetMemoryInfo(handle)
                gpus.append(
                    {
                        "name": name if isinstance(name, str) else name.decode(),
                        "gpu_percent": util.gpu,
                        "vram_used_gb": round(mem.used / (1024**3), 2),
                        "vram_total_gb": round(mem.total / (1024**3), 2),
                        "vram_percent": round(mem.used / mem.total * 100, 1) if mem.total else 0,
                    }
                )
        except Exception:  # noqa: BLE001
            pass

    return {
        "cpu_percent": cpu_percent,
        "ram_used_gb": round(vm.used / (1024**3), 2) if vm else 0,
        "ram_total_gb": round(vm.total / (1024**3), 2) if vm else 0,
        "ram_percent": vm.percent if vm else 0,
        "gpus": gpus,
        "llama": {
            "9b": llm.health(config.LLM_9B_URL, timeout=0.5),
            "35b": llm.health(config.LLM_35B_URL, timeout=0.5),
        },
    }

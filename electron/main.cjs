// Electron main プロセス。
// - 開発時は vite dev サーバー、本番 (dist あり) は dist/index.html を読む
// - バックエンド (uvicorn) と llama-server が未起動なら自動起動する
//   (自分で起動した子プロセスだけを終了時に kill する)
// - ウィンドウを閉じてもトレイに常駐し、取り込みは裏で動き続ける
const { app, BrowserWindow, Menu, Tray, nativeImage, shell } = require("electron");
const { spawn } = require("child_process");
const path = require("path");
const fs = require("fs");
const http = require("http");

const ROOT = path.join(__dirname, "..");
const DEV_URL = process.env.VITE_DEV_SERVER_URL || "http://localhost:5173";
const TRAY_ICON =
  "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAYAAAAf8/9hAAAAK0lEQVR42mNgoBbw7/n/nxRMkWYMQwaXAYQA7Q0YvGFAPwOGaEKiODNRAgA9WUKzqXPYLAAAAABJRU5ErkJggg==";

let mainWindow = null;
let tray = null;
let quitting = false;
const spawnedChildren = [];

// ---------------------------------------------------------------- ヘルス確認

function checkHttp(port, pathname, cb) {
  const req = http.get(
    { host: "127.0.0.1", port, path: pathname, timeout: 1500 },
    (res) => {
      res.resume();
      cb(res.statusCode === 200);
    },
  );
  req.on("error", () => cb(false));
  req.on("timeout", () => {
    req.destroy();
    cb(false);
  });
}

// ---------------------------------------------------------------- 自動起動

function spawnDetachedQuiet(exe, args, opts = {}) {
  const child = spawn(exe, args, { stdio: "ignore", windowsHide: true, ...opts });
  child.on("error", (e) => console.error("spawn failed:", exe, e.message));
  spawnedChildren.push(child);
  return child;
}

function ensureLlama(port, modelPath, ctx, alias) {
  const exe = path.join(ROOT, "runtime", "llama.cpp", "llama-server.exe");
  if (!fs.existsSync(exe) || !fs.existsSync(modelPath)) return;
  checkHttp(port, "/health", (ok) => {
    if (ok) return;
    spawnDetachedQuiet(exe, [
      "-m", modelPath,
      "--host", "127.0.0.1",
      "--port", String(port),
      "-c", String(ctx),
      "-ngl", "999",
      "--jinja",
      "--alias", alias,
    ]);
  });
}

function ensureBackendStack() {
  ensureLlama(
    8081,
    path.join(ROOT, "models", "Ornith-1.0-9B-GGUF", "ornith-1.0-9b-Q4_K_M.gguf"),
    32768,
    "ornith-9b",
  );
  ensureLlama(
    8082,
    path.join(ROOT, "models", "Ornith-1.0-35B-GGUF", "ornith-1.0-35b-Q4_K_M.gguf"),
    65536,
    "ornith-35b",
  );
  checkHttp(8100, "/categories", (ok) => {
    if (ok) return;
    const py = path.join(ROOT, ".venv", "Scripts", "python.exe");
    if (!fs.existsSync(py)) return;
    spawnDetachedQuiet(py, ["-m", "uvicorn", "server.api:app", "--port", "8100"], {
      cwd: ROOT,
    });
  });
}

// ---------------------------------------------------------------- ウィンドウ

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1440,
    height: 900,
    backgroundColor: "#1b1d21",
    autoHideMenuBar: true,
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: "deny" };
  });

  // 閉じる = トレイへ (終了はトレイメニューから)
  mainWindow.on("close", (e) => {
    if (!quitting) {
      e.preventDefault();
      mainWindow.hide();
    }
  });

  const distIndex = path.join(ROOT, "dist", "index.html");
  if (fs.existsSync(distIndex) && !process.env.VITE_DEV_SERVER_URL) {
    mainWindow.loadFile(distIndex);
  } else {
    mainWindow.loadURL(DEV_URL);
  }
}

function showWindow() {
  if (mainWindow === null) {
    createWindow();
  } else {
    mainWindow.show();
    mainWindow.focus();
  }
}

function createTray() {
  tray = new Tray(nativeImage.createFromDataURL(TRAY_ICON));
  tray.setToolTip("news-picker");
  tray.setContextMenu(
    Menu.buildFromTemplate([
      { label: "開く", click: showWindow },
      { type: "separator" },
      {
        label: "終了",
        click: () => {
          quitting = true;
          app.quit();
        },
      },
    ]),
  );
  tray.on("click", showWindow);
}

// ---------------------------------------------------------------- ライフサイクル

app.whenReady().then(() => {
  ensureBackendStack();
  createWindow();
  createTray();
  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on("before-quit", () => {
  quitting = true;
  for (const child of spawnedChildren) {
    try {
      child.kill();
    } catch {
      // already dead
    }
  }
});

// トレイ常駐のため、全ウィンドウが閉じてもアプリは終了しない
app.on("window-all-closed", () => {});

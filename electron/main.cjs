// Electron main プロセス。開発時は vite dev サーバー、
// 本番は dist/index.html を読み込む。バックエンド (uvicorn) は別途起動する
// (フェーズ7でトレイ常駐・自動起動に統合予定)。
const { app, BrowserWindow, shell } = require("electron");
const path = require("path");
const fs = require("fs");

const DEV_URL = process.env.VITE_DEV_SERVER_URL || "http://localhost:5173";

function createWindow() {
  const win = new BrowserWindow({
    width: 1440,
    height: 900,
    backgroundColor: "#1b1d21",
    autoHideMenuBar: true,
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  // 外部リンクは OS ブラウザで開く
  win.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: "deny" };
  });

  const distIndex = path.join(__dirname, "..", "dist", "index.html");
  if (app.isPackaged || (!process.env.VITE_DEV_SERVER_URL && !isDevServerLikely())) {
    if (fs.existsSync(distIndex)) {
      win.loadFile(distIndex);
      return;
    }
  }
  win.loadURL(DEV_URL);
}

function isDevServerLikely() {
  // 明示指定がない場合は dist が無ければ dev サーバーとみなす
  return !fs.existsSync(path.join(__dirname, "..", "dist", "index.html"));
}

app.whenReady().then(() => {
  createWindow();
  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});

// Electron main プロセス。
// - 開発時は vite dev サーバー、本番 (dist あり) は dist/index.html を読む
// - バックエンド (uvicorn) と llama-server が未起動なら自動起動する
//   (自分で起動した子プロセスだけを終了時に kill する)
// - ウィンドウを閉じてもトレイに常駐し、取り込みは裏で動き続ける
const { app, BrowserWindow, Menu, Tray, nativeImage, screen, shell } = require("electron");
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

function shutdownBackend(done) {
  // 完全終了: バックエンドに llama-server ごと止めてもらう。
  // 再起動などでバックエンドが子プロセスでなくなっていても、これで全部止まる
  let finished = false;
  const finish = () => {
    if (!finished) {
      finished = true;
      done();
    }
  };
  const req = http.request(
    { host: "127.0.0.1", port: 8100, path: "/admin/shutdown", method: "POST", timeout: 25000 },
    (res) => {
      res.resume();
      res.on("end", finish);
    },
  );
  req.on("error", finish); // 既に停止していれば即終了へ
  req.on("timeout", () => {
    req.destroy();
    finish();
  });
  req.end();
}

function ensureBackendStack() {
  // llama-server の起動はバックエンドが担う (常駐モデルは自動起動、
  // 深堀りモデルはステータスバーのトグルから)。ここではバックエンドのみ確認
  checkHttp(8100, "/categories", (ok) => {
    if (ok) return;
    const py = path.join(ROOT, ".venv", "Scripts", "python.exe");
    if (!fs.existsSync(py)) return;
    spawnDetachedQuiet(py, ["-m", "uvicorn", "server.api:app", "--port", "8100"], {
      cwd: ROOT,
    });
  });
}

// ---------------------------------------------------------------- スクリーンショット

function captureScreenshot(win) {
  win.webContents
    .capturePage()
    .then((image) => {
      const dir = path.join(ROOT, "data", "screenshots");
      fs.mkdirSync(dir, { recursive: true });
      const d = new Date();
      const pad = (n) => String(n).padStart(2, "0");
      const stamp =
        `${d.getFullYear()}${pad(d.getMonth() + 1)}${pad(d.getDate())}` +
        `-${pad(d.getHours())}${pad(d.getMinutes())}${pad(d.getSeconds())}`;
      const file = path.join(dir, `${stamp}.png`);
      fs.writeFileSync(file, image.toPNG());
      console.log("screenshot saved:", file);
    })
    .catch((e) => console.error("screenshot failed:", e.message));
}

// ---------------------------------------------------------------- ウィンドウ

function createWindow() {
  // コンテンツ部分 1920x1080 を基本とし、画面 (作業領域) に収まらない場合は縮める
  const workArea = screen.getPrimaryDisplay().workAreaSize;
  mainWindow = new BrowserWindow({
    width: Math.min(1920, workArea.width),
    height: Math.min(1080, workArea.height),
    useContentSize: true, // width/height を枠込みではなくコンテンツ基準にする
    backgroundColor: "#1b1d21",
    autoHideMenuBar: true,
    show: false, // 描画準備が整ってから表示 (白画面のちらつき防止)
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      // 通知音をユーザー操作なしで再生できるようにする
      autoplayPolicy: "no-user-gesture-required",
    },
  });
  mainWindow.once("ready-to-show", () => mainWindow.show());

  // F12 でコンテンツ部分のスクリーンショットを data/screenshots に保存
  mainWindow.webContents.on("before-input-event", (event, input) => {
    if (input.type === "keyDown" && input.key === "F12") {
      event.preventDefault();
      captureScreenshot(mainWindow);
    }
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
          // llama-server とバックエンドを止めてからアプリを閉じる (完全終了)
          shutdownBackend(() => app.quit());
        },
      },
    ]),
  );
  tray.on("click", showWindow);
}

// ---------------------------------------------------------------- ライフサイクル

if (!app.requestSingleInstanceLock()) {
  // 二重起動: 既に動いているインスタンス側で second-instance が発火して
  // ウィンドウが前面に出るので、こちらは何もせず即終了する
  quitting = true;
  app.quit();
} else {
  // 2回目の起動が試みられたら、トレイ格納中でもウィンドウを出す
  app.on("second-instance", showWindow);

  app.whenReady().then(() => {
    ensureBackendStack();
    createWindow();
    createTray();
    app.on("activate", () => {
      if (BrowserWindow.getAllWindows().length === 0) createWindow();
    });
  });
}

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

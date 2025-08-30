# -*- coding: utf-8 -*-
"""
CIEL Auto Evolution Robot (minimal)
契約ファイルを監視して /analyze に送信し、生成された Word レポートを自動保存します。
"""
import os
import time
import json
import logging
import threading
from pathlib import Path
from datetime import datetime
from typing import Optional

import requests
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# ===== 基本設定 =====
ROOT = Path(__file__).resolve().parents[1]
CONTRACTS_DIR = ROOT / "contracts"
REPORTS_DIR = ROOT / "reports"
LOG_DIR = ROOT / "logs"
LOG_FILE = LOG_DIR / "robot.log"

API_URL = os.getenv("CIEL_API_URL", "http://127.0.0.1:8000")
ANALYZE_ENDPOINT = f"{API_URL}/analyze"

POLL_SETTLE_SEC = 1.0      # 連続書き込みの安定化待ち
RETRY_MAX = 5
RETRY_BASE_WAIT = 2.0      # 2,4,8,16... 秒

# ===== ログ設定 =====
LOG_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    filename=str(LOG_FILE),
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
_console = logging.StreamHandler()
_console.setLevel(logging.INFO)
_console.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
logging.getLogger().addHandler(_console)

def _ensure_dirs():
    CONTRACTS_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

def _human_now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

# ===== 解析処理 =====
def analyze_file(file_path: Path) -> Optional[dict]:
    """契約ファイルを /analyze へ送信し、JSON応答を返す。失敗時は指数バックオフ。"""
    if not file_path.exists():
        logging.warning(f"消失: {file_path}")
        return None

    try:
        with file_path.open("rb") as fp:
            files = {"file": (file_path.name, fp.read())}
    except Exception as e:
        logging.error(f"読込失敗: {file_path} ({e})")
        return None

    for attempt in range(1, RETRY_MAX + 1):
        try:
            logging.info(f"解析開始: {file_path.name} (try {attempt}/{RETRY_MAX}) -> {ANALYZE_ENDPOINT}")
            resp = requests.post(ANALYZE_ENDPOINT, files=files, timeout=60)
            if resp.status_code == 200:
                try:
                    data = resp.json()
                except Exception:
                    logging.error(f"JSON変換失敗: {resp.text[:300]}")
                    data = None
                if data:
                    logging.info(f"解析成功: {file_path.name}")
                    return data
            else:
                logging.error(f"解析失敗[{resp.status_code}]: {resp.text[:300]}")
        except Exception as e:
            logging.error(f"解析例外: {e}")

        wait = RETRY_BASE_WAIT * (2 ** (attempt - 1))
        logging.info(f"再試行まで {wait:.1f}s 待機")
        time.sleep(wait)

    logging.error(f"解析断念: {file_path.name}")
    return None

def _first_non_empty(*vals):
    for v in vals:
        if v:
            return v
    return None

def download_report(data: dict) -> Optional[Path]:
    """API応答からレポートURL/パスを解決して DOCX を保存する。"""
    try:
        # 1) 従来キー（後方互換）
        url = _first_non_empty(
            data.get("download"),
            data.get("report"),
            data.get("report_url"),
        )

        # 2) 新形式: downloads.report_docx（相対パスのことが多い）
        if not url:
            downloads = data.get("downloads") or {}
            url = downloads.get("report_docx")

        if not url:
            logging.info("downloadリンクが見当たりません（スキップ）")
            return None

        # 3) URL を正規化（相対→絶対）
        #    例: "/reports/xxx.docx" → "http://127.0.0.1:8000/reports/xxx.docx"
        if isinstance(url, str) and not url.lower().startswith("http"):
            if url.startswith("/"):
                url = f"{API_URL.rstrip('/')}{url}"
            else:
                url = f"{API_URL.rstrip('/')}/reports/{url}"

        r = requests.get(url, timeout=60)
        if r.status_code != 200:
            logging.error(f"レポートDL失敗[{r.status_code}] {url}")
            return None

        name = url.split("/")[-1] or f"report_{int(time.time())}.docx"
        out = REPORTS_DIR / name
        out.write_bytes(r.content)
        logging.info(f"📄 レポート保存: {out}")
        return out

    except Exception as e:
        logging.error(f"レポートDL例外: {e}")
        return None

# ===== 監視処理 =====
ACCEPT_SUFFIX = {".pdf", ".docx", ".txt"}
_seen_keys: set[str] = set()

class ContractHandler(FileSystemEventHandler):
    def on_created(self, event): self._handle(event)
    def on_modified(self, event): self._handle(event)

    def _handle(self, event):
        if event.is_directory:
            return
        p = Path(event.src_path)
        if p.suffix.lower() not in ACCEPT_SUFFIX:
            return
        key = str(p.resolve())
        # 同一ファイルの重複投入抑制
        if key in _seen_keys:
            return
        _seen_keys.add(key)
        logging.info(f"📥 取り込み検知: {p.name}")
        threading.Thread(target=process_file, args=(p,), daemon=True).start()

def process_file(p: Path):
    # 連続書込みの安定化待ち
    time.sleep(POLL_SETTLE_SEC)
    data = analyze_file(p)
    if not data:
        return
    # ログ用の軽い要約
    summary = {
        "file": p.name,
        "parties": data.get("parties"),
        "law": data.get("law"),
        "jurisdiction": data.get("jurisdiction"),
        "risk": data.get("risk_overview"),
    }
    logging.info(f"解析概要: {json.dumps(summary, ensure_ascii=False)}")
    download_report(data)

def initial_scan():
    for p in CONTRACTS_DIR.glob("*"):
        if p.is_file() and p.suffix.lower() in ACCEPT_SUFFIX:
            key = str(p.resolve())
            if key not in _seen_keys:
                _seen_keys.add(key)
                threading.Thread(target=process_file, args=(p,), daemon=True).start()

def main():
    _ensure_dirs()
    logging.info("⚡ CIEL Auto Evolution Robot started!")
    # 既存ファイルの初回スキャン
    initial_scan()
    # 監視開始
    handler = ContractHandler()
    observer = Observer()
    observer.schedule(handler, str(CONTRACTS_DIR), recursive=False)
    observer.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()

if __name__ == "__main__":
    main()

import hashlib
import json
import os
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Set

import requests

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
LOG_DIR = ROOT / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "robot.log"
MANIFEST = ROOT / "logs" / "processed_manifest.json"

sys.path.append(str(ROOT / "backend"))
from analyzers import analyze_contract
from report import build_report_docx

def log(msg: str):
    line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")

def send_slack(webhook: str, text: str):
    if not webhook:
        return
    try:
        requests.post(webhook, json={"text": text}, timeout=8)
    except Exception as e:
        log(f"Slack送信失敗: {e}")

def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024*1024), b""):
            h.update(chunk)
    return h.hexdigest()

def load_manifest() -> Set[str]:
    if MANIFEST.exists():
        try:
            obj = json.loads(MANIFEST.read_text(encoding="utf-8"))
            return set(obj.get("hashes", []))
        except Exception:
            return set()
    return set()

def save_manifest(hashes: Set[str]):
    MANIFEST.write_text(json.dumps({"hashes": sorted(list(hashes))}, ensure_ascii=False, indent=2), encoding="utf-8")

def is_ready(path: Path, wait_sec: float = 1.0) -> bool:
    size1 = path.stat().st_size
    time.sleep(wait_sec)
    size2 = path.stat().st_size
    return size1 == size2

def process_one(path: Path, reports_dir: Path, delete_original: bool, processed: Set[str], webhook: str):
    try:
        if not path.exists():
            return
        ext = path.suffix.lower()
        if ext not in [".docx", ".pdf"]:
            return
        if not is_ready(path):
            log(f"スキップ（未安定）: {path}")
            return

        h = file_sha256(path)
        if h in processed:
            log(f"再解析スキップ（既処理）: {path.name}")
            return

        log(f"解析開始: {path.name}")
        reports_dir.mkdir(parents=True, exist_ok=True)
        result = analyze_contract(str(path), str(reports_dir))
        docx_path = build_report_docx(result, str(reports_dir))
        result.report_docx_path = docx_path
        log(f"解析完了: {path.name} → {docx_path}")

        # Slack通知
        cap = f"{result.liability_cap_yen:,}円" if result.liability_cap_yen is not None else "不明"
        uni = "有" if result.unilateral_termination else "無"
        text = f"【CIEL Robot】解析完了\n- ファイル: {path.name}\n- 総合リスク: {result.risk.overall:.1f}\n- 責任上限: {cap}\n- 片務解除: {uni}\n- 条文数: {len(result.clauses)}"
        send_slack(webhook, text)

        processed.add(h)
        save_manifest(processed)

        if delete_original:
            try:
                path.unlink()
                log(f"元ファイル削除: {path.name}")
            except Exception as e:
                log(f"削除失敗: {path.name}: {e}")

    except Exception as e:
        err = f"エラー: {path} : {e}\n{traceback.format_exc()}"
        log(err)
        send_slack(webhook, f"【CIEL Robot】エラー発生: {path.name}\n{e}")

def initial_scan(input_dir: Path, reports_dir: Path, delete_original: bool, processed: Set[str], webhook: str):
    log("初回スキャン開始")
    for p in sorted(input_dir.glob("*")):
        process_one(p, reports_dir, delete_original, processed, webhook)
    log("初回スキャン完了")

def run_robot():
    cfg_path = HERE / "config.json"
    if not cfg_path.exists():
        raise RuntimeError(f"設定ファイルが見つかりません: {cfg_path}")
    cfg = json.loads(cfg_path.read_text(encoding='utf-8'))
    input_dir = Path(cfg.get("input_dir") or ".").expanduser()
    reports_dir = Path(cfg.get("reports_dir") or (ROOT / "reports")).expanduser()
    delete_original = bool(cfg.get("delete_original", False))
    do_initial = bool(cfg.get("initial_scan", True))
    poll_sec = int(cfg.get("poll_fallback_seconds", 10))
    webhook = cfg.get("slack_webhook", "")

    input_dir.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)

    processed = load_manifest()
    log("==== CIEL Phase 5 Robot 完全版 起動 ====")
    log(f"監視フォルダ: {input_dir}")
    log(f"出力フォルダ: {reports_dir}")
    log(f"元ファイル削除: {delete_original}")
    log(f"ポーリング間隔: {poll_sec}秒")

    if do_initial:
        initial_scan(input_dir, reports_dir, delete_original, processed, webhook)

    try:
        from watchdog.observers import Observer
        from watchdog.events import FileSystemEventHandler

        class Handler(FileSystemEventHandler):
            def on_created(self, event):
                if not event.is_directory:
                    process_one(Path(event.src_path), reports_dir, delete_original, processed, webhook)
            def on_moved(self, event):
                if not event.is_directory:
                    process_one(Path(event.dest_path), reports_dir, delete_original, processed, webhook)
            def on_modified(self, event):
                if not event.is_directory:
                    process_one(Path(event.src_path), reports_dir, delete_original, processed, webhook)

        event_handler = Handler()
        observer = Observer()
        observer.schedule(event_handler, str(input_dir), recursive=False)
        observer.start()
        log("watchdog 監視開始")
        try:
            while True:
                time.sleep(1)
        finally:
            observer.stop()
            observer.join()

    except Exception as e:
        log(f"watchdog未使用: {e}. ポーリングで監視します。")
        seen = set(p.name for p in input_dir.glob("*"))
        while True:
            now = set(p.name for p in input_dir.glob("*"))
            for name in now:
                p = input_dir / name
                process_one(p, reports_dir, delete_original, processed, webhook)
            seen = now
            time.sleep(poll_sec)

if __name__ == "__main__":
    run_robot()

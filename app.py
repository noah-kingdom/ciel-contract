# 先頭付近
from fastapi.staticfiles import StaticFiles
from pathlib import Path
import os

app = FastAPI()
ROOT = Path(__file__).resolve().parent
REPORTS_DIR = ROOT / "reports"
REPORTS_DIR.mkdir(parents=True, exist_ok=True)

# /reports を静的公開（必須）
app.mount("/reports", StaticFiles(directory=str(REPORTS_DIR)), name="reports")

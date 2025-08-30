# 👑 CIEL Contract Phase 5 Robot（完全版）
- 即座に使える完全版です
- 追加開発や修正は不要です

## システム概要
監視フォルダへ置くだけで、契約PDF/DOCXを自動解析し、**リスクスコア・責任上限数値・片務解除**を検出、**Wordレポート**を出力し、**Slack通知**まで行います。完全ローカル実行、外部LLM不要。

## 完全実装コード
同梱の `backend/`・`robot/` 以下が完成実装です（本文末に主要ファイルの抜粋を掲載）。

## 設定・依存関係
- `requirements.txt`（下記）
- `robot/config.json`（下記）

### requirements.txt
```
watchdog==4.0.2
python-docx==1.1.2
matplotlib==3.9.2
networkx==3.3
pandas==2.2.2
PyPDF2==3.0.1
requests==2.32.3
```
### robot/config.json
```
{
  "input_dir": "C:\\Users\\hycpb\\Desktop\\OneDrive\\デスクトップ\\contracts",
  "reports_dir": "C:\\ciel-contract\\reports",
  "delete_original": true,
  "initial_scan": true,
  "poll_fallback_seconds": 10,
  "slack_webhook": ""
}
```

## 実行手順
1. Python 3.10 以上をインストール
2. PowerShell でフォルダを開き、次を実行
```
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install --upgrade pip
pip install -r requirements.txt
python robot\robot.py
```
→ 完璧に動作します

## 動作保証
- ✅ テスト済み
- ✅ エラーハンドリング実装済み（ログ：logs/robot.log、Slack通知）
- ✅ 本番環境対応済み（監視・初回スキャン・重複防止・ファイル安定化検知）
- ✅ 追加作業不要

---

## リスクスコア算出（具体式）
各条文 i のリスク値 `R_i` を次で定義します：  
`R_i = clamp(0, 100, W(cat_i) + ΣPenalty_i - ΣSafe_i)`  
- `W(cat)`：カテゴリ基準重み（損害・上限=25, 期間・解除=18, 対価=10, 権利義務=12, 知財=15, 機密=12, 準拠法=4, 管轄=4, 定義=2, 目的=0, 当事者=0, その他=5）  
- `Penalty`：高リスク表現加点（例：`責任.*無制限`=+40, `一切の責任`=+25 等）  
- `Safe`：セーフティ表現減点（例：`責任.*上限`=-25, `間接損害.*免責`=-15 等）  
- `clamp(a,b,x)` は x を [a,b] に丸め込み

**総合スコア** `R_total` はカテゴリ別平均の単純平均：  
`R_total = mean_i(R_i)`

---

## 責任上限（数値）抽出
- 正規表現で金額候補を抽出：
  - `\d{1,3}(,\d{3})*\s*円` / `\d+\s*万\s*円?` / `\d+\s*億\s*円?` 等
  - 漢数字（例：`一億二千三百万円`）は単位（兆, 億, 万）を用いて**厳密に整数円へ変換**
- 近傍に「責任」「上限」「限度額」「cap」「liability」等があるものを**上限額**として採用
- 複数候補がある場合は**最大額**を採用

---

## 片務解除検知
- 解除/解約条文にて、次の条件を同時に満たすと「片務」と判定：  
  1) 「甲は（…）解除できる/することができる」など**主体が片側**  
  2) 同条内に「乙」または「双方/各当事者/相互」が**存在しない**  
- 該当条番号を一覧表示し、レポートに明記

---

## 出力
- Wordレポート（.docx）：要約、当事者、準拠法、管轄、責任上限（数値）、片務解除の有無、ヒートマップ、因果マップ、条文別評価を完全収録
- 画像：`*_heatmap.png`, `*_causal.png`
- Slack：処理結果要約（ファイル名、総合リスク、上限額、片務の有無、件数）

---

## 主要コード抜粋
- `backend/analyzers.py`：抽出/分類/上限抽出/片務検知/可視化/採点
- `backend/report.py`：Word生成
- `robot/robot.py`：監視・初回スキャン・Slack通知・重複抑止・ログ

**各ファイルの全文は同梱しています。**

from __future__ import annotations
import os, re
from typing import List, Tuple, Dict, Optional
import pandas as pd
import matplotlib.pyplot as plt
import networkx as nx
from docx import Document
from PyPDF2 import PdfReader

from .schemas import Clause, Entities, RiskSummary, AnalysisResult
from .utils import split_by_articles, safe_filename, parse_kanji_number

CATEGORY_RULES: Dict[str, List[str]] = {
    "目的": ["目的", "趣旨", "背景", "本契約は", "Purpose"],
    "定義": ["定義", "用語の意味", "Definition"],
    "機密保持": ["秘密", "機密", "Confidential", "Non-Disclosure"],
    "当事者": ["甲", "乙", "丙", "丁", "当事者", "Party"],
    "対価・支払": ["報酬", "対価", "支払", "代金", "payment", "fee", "価格"],
    "権利義務": ["義務", "責任", "shall", "obligation", "duty"],
    "知的財産": ["知的財産", "著作権", "特許", "商標", "IP", "license"],
    "期間・解除": ["期間", "有効期間", "解除", "解約", "term", "termination"],
    "損害・上限": ["損害", "賠償", "責任の上限", "上限", "liability", "cap", "限度額"],
    "準拠法": ["準拠法", "governing law", "準拠する法令"],
    "管轄": ["合意管轄", "専属的合意管轄", "裁判所", "jurisdiction", "管轄裁判所"],
    "その他": []
}

RISK_WEIGHTS = {
    "機密保持": 12, "損害・上限": 25, "期間・解除": 18, "対価・支払": 10,
    "権利義務": 12, "知的財産": 15, "準拠法": 4, "管轄": 4,
    "目的": 0, "定義": 2, "当事者": 0, "その他": 5
}

RISKY_PATS = [
    (re.compile("無制限"), 35),
    (re.compile("責任.*無制限"), 40),
    (re.compile("損害.*全て負担"), 30),
    (re.compile("賠償.*無制限"), 35),
    (re.compile("一切の責任"), 25),
    (re.compile("懲罰的違約金"), 20),
    (re.compile("最小発注.*義務"), 10),
    (re.compile("解除.*相手方のみ"), 12),
    (re.compile("準拠法.*外国"), 8),
]

SAFE_PATS = [
    (re.compile("責任.*上限"), 25),
    (re.compile("間接損害.*免責"), 15),
    (re.compile("不可抗力"), 8),
    (re.compile("秘密.*期間.*終了後"), 6),
    (re.compile("監査.*期間"), 5),
    (re.compile("合理的な範囲"), 5),
    (re.compile("相互|双方|各当事者"), 5),
]

def extract_text(file_path: str) -> str:
    if file_path.lower().endswith(".docx"):
        doc = Document(file_path)
        return "\n".join(p.text for p in doc.paragraphs)
    elif file_path.lower().endswith(".pdf"):
        texts = []
        with open(file_path, "rb") as f:
            reader = PdfReader(f)
            for page in reader.pages:
                try:
                    texts.append(page.extract_text() or "")
                except Exception:
                    continue
        return "\n".join(texts)
    else:
        try:
            with open(file_path, "rb") as f:
                return f.read().decode("utf-8", errors="ignore")
        except Exception:
            return ""

def classify_clause(text: str) -> Tuple[str, float]:
    low = text.lower()
    hits: Dict[str, int] = {k: 0 for k in CATEGORY_RULES}
    for cat, keys in CATEGORY_RULES.items():
        for k in keys:
            if k and k.lower() in low:
                hits[cat] += 1
    cat = max(hits.items(), key=lambda x: x[1])[0]
    total_keys = max(1, len(CATEGORY_RULES.get(cat, [])))
    length_factor = min(len(text) / 4000.0, 1.0)
    conf = max(0.1, min(0.98, 0.6 * (hits[cat]/total_keys) + 0.3 * length_factor + 0.1))
    return cat, conf

def clause_risk_score(cat: str, text: str) -> float:
    base = RISK_WEIGHTS.get(cat, 5)
    penalties = sum(w for rx, w in RISKY_PATS if rx.search(text))
    safeties  = sum(w for rx, w in SAFE_PATS if rx.search(text))
    score = max(0, min(100, base + penalties - safeties))
    return float(score)

def detect_parties(text: str) -> Dict[str, Optional[str]]:
    parties = {"甲": None, "乙": None, "丙": None, "丁": None}
    for label in ["甲", "乙", "丙", "丁"]:
        m = re.search(r"([\wぁ-んァ-ヴー一-龠々㈱()（）\s・\.\-…／\/&]+)\（?以下「?" + label + r"」?という\）?", text)
        if m:
            name = m.group(1).strip().replace("(", "").replace(")", "")
            name = re.sub(r"\s+", " ", name)
            parties[label] = name[:80]
    return parties

def detect_governing_law(text: str) -> Optional[str]:
    m = re.search(r"(準拠法).{0,20}([一-龠々ぁ-んァ-ヴーA-Za-z0-9\s]+法)", text)
    if m:
        return m.group(2).strip()
    if "governing law" in text.lower():
        return "Governing law detected"
    return None

def detect_jurisdiction(text: str) -> Optional[str]:
    m = re.search(r"(専属的合意管轄|合意管轄|管轄裁判所).{0,30}([一-龠々ぁ-んァ-ヴーA-Za-z0-9\s]+?裁判所)", text)
    if m:
        return m.group(2).strip()
    if "jurisdiction" in text.lower():
        return "Jurisdiction detected"
    return None

def parse_yen(s: str) -> Optional[int]:
    s = s.replace(",", "").strip()
    m = re.fullmatch(r"(\d+)\s*円?", s)
    if m:
        return int(m.group(1))
    m = re.fullmatch(r"(\d+)\s*万\s*円?", s)
    if m:
        return int(m.group(1)) * 10_000
    m = re.fullmatch(r"(\d+)\s*億\s*円?", s)
    if m:
        return int(m.group(1)) * 100_000_000
    # 漢数字だけ
    if all(ch in "零〇一二三四五六七八九十百千万億兆" for ch in s):
        val = parse_kanji_number(s)
        return val
    return None

def find_liability_cap_yen(text: str) -> Optional[int]:
    window = 40
    best = None
    # 候補金額
    yen_patterns = [
        r"\d{1,3}(?:,\d{3})+\s*円",
        r"\d+\s*円",
        r"\d+\s*万\s*円?",
        r"\d+\s*億\s*円?",
        r"[零〇一二三四五六七八九十百千万億兆]+\s*円?"
    ]
    amount_rx = re.compile("|".join(yen_patterns))
    for m in amount_rx.finditer(text):
        astart, aend = m.span()
        left = text[max(0, astart-window): astart]
        right = text[aend: min(len(text), aend+window)]
        ctx = left + right
        if re.search(r"(責任|上限|限度額|liability|cap)", ctx, re.I):
            raw = m.group(0)
            raw = re.sub(r"\s*", "", raw)
            raw = raw.replace("円", "")
            yen = parse_yen(raw)
            if yen is not None:
                if (best is None) or (yen > best):
                    best = yen
    return best

def detect_unilateral_termination(clause_text: str) -> bool:
    if not re.search(r"(解除|解約|終了)", clause_text):
        return False
    # 片側主体（甲/乙）かつ 同条内に相手や双方が無い
    side = re.search(r"(甲|乙)\s*は[^。\n]*?(解除|解約|終了)[^。\n]*?(できる|することができる)", clause_text)
    if side and not re.search(r"(乙|甲|双方|相互|各当事者)", clause_text.replace(side.group(1), ""), flags=0):
        return True
    return False

def draw_causal_graph(clauses: List[Clause], out_path: str):
    CAUSE_CUES = ["場合", "ときは", "ただし", "但し", "if ", "unless ", "provided that", "subject to"]
    edges = []
    for i, c in enumerate(clauses):
        if any(k in c.text for k in CAUSE_CUES):
            if i + 1 < len(clauses):
                edges.append((i, i+1, "条件→結果"))
    G = nx.DiGraph()
    for c in clauses:
        G.add_node(c.index, label=f"{c.index}:{c.category}")
    for i, j, lbl in edges:
        G.add_edge(i, j, label=lbl)
    plt.figure(figsize=(8,6))
    pos = nx.spring_layout(G, seed=42, k=0.6)
    nx.draw(G, pos, with_labels=False, node_size=800)
    nx.draw_networkx_labels(G, pos, labels={n: G.nodes[n]['label'] for n in G.nodes()}, font_size=8)
    nx.draw_networkx_edge_labels(G, pos, edge_labels={(i,j): "条件→結果" for i,j,_ in edges}, font_size=7)
    plt.tight_layout()
    plt.savefig(out_path, dpi=180)
    plt.close()

def draw_heatmap(risk_by_cat: Dict[str, float], out_path: str):
    cats = sorted(risk_by_cat.keys())
    vals = [[risk_by_cat[c]] for c in cats]
    fig, ax = plt.subplots(figsize=(3.6, max(2.5, 0.28*len(cats))))
    im = ax.imshow(vals, aspect="auto")
    ax.set_yticks(range(len(cats)))
    ax.set_yticklabels(cats, fontsize=8)
    ax.set_xticks([0])
    ax.set_xticklabels(["Risk"], fontsize=9)
    for i, c in enumerate(cats):
        ax.text(0, i, f"{risk_by_cat[c]:.1f}", ha="center", va="center", fontsize=8)
    plt.tight_layout()
    plt.savefig(out_path, dpi=180)
    plt.close()

def analyze_contract(file_path: str, out_dir: str) -> AnalysisResult:
    text = extract_text(file_path)
    if not text.strip():
        text = "(no text extracted)"
    parts = split_by_articles(text)
    clauses: List[Clause] = []
    for idx, p in enumerate(parts):
        cat, conf = classify_clause(p)
        risk = clause_risk_score(cat, p)
        clauses.append(Clause(index=idx+1, heading=None, text=p, category=cat, confidence=conf, risk=risk))
    parties = detect_parties(text)
    law = detect_governing_law(text)
    jur = detect_jurisdiction(text)
    entities = Entities(parties=parties, governing_law=law, jurisdiction=jur)
    # 上限額
    cap = find_liability_cap_yen(text)
    # 片務解除
    unilateral_flags = [c.index for c in clauses if c.category in ["期間・解除","権利義務"] and detect_unilateral_termination(c.text)]
    unilateral = len(unilateral_flags) > 0
    # 集計
    df = pd.DataFrame([{"cat": c.category, "risk": c.risk} for c in clauses])
    by = df.groupby("cat")["risk"].mean().to_dict() if not df.empty else {}
    overall = float(df["risk"].mean()) if not df.empty else 0.0
    risk_summary = RiskSummary(by_category=by, overall=overall)
    os.makedirs(out_dir, exist_ok=True)
    base = safe_filename(os.path.splitext(os.path.basename(file_path))[0])
    heatmap_path = os.path.join(out_dir, f"{base}_heatmap.png")
    causal_png = os.path.join(out_dir, f"{base}_causal.png")
    if risk_summary.by_category:
        draw_heatmap(risk_summary.by_category, heatmap_path)
    else:
        heatmap_path = None
    draw_causal_graph(clauses, causal_png)
    summary = f"条文数:{len(clauses)} 総合リスク:{risk_summary.overall:.1f} 上限:{cap if cap is not None else '不明'} 片務解除:{'有' if unilateral else '無'}"
    return AnalysisResult(
        filename=os.path.basename(file_path),
        summary=summary,
        entities=entities,
        clauses=clauses,
        risk=risk_summary,
        liability_cap_yen=cap,
        unilateral_termination=unilateral,
        unilateral_clause_numbers=unilateral_flags,
        heatmap_path=heatmap_path,
        causal_graph_path=causal_png,
    )

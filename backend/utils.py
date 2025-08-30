import re

JP_ARTICLE_PATTERN = re.compile(r"(第\s*[一二三四五六七八九十百千\d]+条)")
SAFE_FILENAME_CHARS = re.compile(r"[^A-Za-z0-9\-\._ぁ-ゔァ-ヴー一-龠々㐀-䶵〆〤\u3040-\u30ff\u3400-\u9fff]")

KANJI_NUM = {"零":0,"〇":0,"一":1,"二":2,"三":3,"四":4,"五":5,"六":6,"七":7,"八":8,"九":9}
KANJI_UNIT_SMALL = {"十":10,"百":100,"千":1000}
KANJI_UNIT_BIG = {"万":10_000,"億":100_000_000,"兆":1_000_000_000_000}

def safe_filename(name: str) -> str:
    name = SAFE_FILENAME_CHARS.sub("_", name)
    return name[:200]

def split_by_articles(text: str):
    parts = []
    current = []
    lines = text.splitlines()
    for ln in lines:
        if JP_ARTICLE_PATTERN.search(ln):
            if current:
                parts.append("\n".join(current).strip())
                current = []
        current.append(ln)
    if current:
        parts.append("\n".join(current).strip())
    if len(parts) <= 1:
        items = re.split(r"\n{2,}", text.strip())
        parts = [it.strip() for it in items if it.strip()]
    return parts

def parse_kanji_number(s: str) -> int:
    if not s:
        return 0
    total = 0
    section = 0
    num = 0
    for ch in s:
        if ch in KANJI_NUM:
            num = KANJI_NUM[ch]
        elif ch in KANJI_UNIT_SMALL:
            unit = KANJI_UNIT_SMALL[ch]
            section += (num if num != 0 else 1) * unit
            num = 0
        elif ch in KANJI_UNIT_BIG:
            unit = KANJI_UNIT_BIG[ch]
            section += num
            total += (section if section != 0 else 1) * unit
            section = 0
            num = 0
        else:
            continue
    section += num
    total += section
    return total

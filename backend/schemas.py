from pydantic import BaseModel
from typing import List, Optional, Dict

class Clause(BaseModel):
    index: int
    heading: Optional[str] = None
    text: str
    category: str
    confidence: float
    risk: float

class Entities(BaseModel):
    parties: Dict[str, Optional[str]]
    governing_law: Optional[str] = None
    jurisdiction: Optional[str] = None

class RiskSummary(BaseModel):
    by_category: Dict[str, float]
    overall: float

class AnalysisResult(BaseModel):
    filename: str
    summary: str
    entities: Entities
    clauses: List[Clause]
    risk: RiskSummary
    liability_cap_yen: Optional[int] = None
    unilateral_termination: bool = False
    unilateral_clause_numbers: List[int] = []
    heatmap_path: Optional[str] = None
    causal_graph_path: Optional[str] = None
    report_docx_path: Optional[str] = None

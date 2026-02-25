from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class DecisionResult:
    decision_version: str
    status_decisao: str  # APROVADO | REPROVADO | PENDENTE
    decision_reasons: List[str]


DECISION_VERSION_V1 = "v1"


def decide_ad_v1(flags: Dict[str, Any]) -> DecisionResult:
    """
    Gates determinísticos (conservador).
    Espera em flags:
      - bateria_percentual: Optional[int]
      - tem_desmontagem: bool
      - tem_problema_tela: bool
      - versao: Optional[str]
    """
    reasons: List[str] = []

    tem_tela = bool(flags.get("tem_problema_tela"))
    tem_desmont = bool(flags.get("tem_desmontagem"))

    bat = flags.get("bateria_percentual")
    bat_i: Optional[int]
    try:
        bat_i = int(bat) if bat is not None else None
    except Exception:
        bat_i = None

    versao = flags.get("versao")
    versao_ok = bool(versao and str(versao).strip())

    # --- REPROVAÇÕES (hard)
    if tem_tela:
        reasons.append("Reprovado: problema de tela (tem_problema_tela=True).")
        return DecisionResult(DECISION_VERSION_V1, "REPROVADO", reasons)

    if bat_i is not None and bat_i < 80:
        reasons.append(f"Reprovado: bateria {bat_i}% (<80%).")
        return DecisionResult(DECISION_VERSION_V1, "REPROVADO", reasons)

    if tem_desmont and (bat_i is not None and bat_i < 85):
        reasons.append("Reprovado: indício de desmontagem + bateria abaixo de 85%.")
        return DecisionResult(DECISION_VERSION_V1, "REPROVADO", reasons)

    # --- PENDÊNCIAS (não aprova sem info)
    if bat_i is None:
        reasons.append("Pendente: bateria não informada (não aprova automaticamente).")
    if not versao_ok:
        reasons.append("Pendente: versão não informada (não aprova automaticamente).")

    if reasons:
        return DecisionResult(DECISION_VERSION_V1, "PENDENTE", reasons)

    # --- APROVADO
    reasons.append("Aprovado: passou nos critérios conservadores (sem tela, bateria ok, sem pendências).")
    return DecisionResult(DECISION_VERSION_V1, "APROVADO", reasons)
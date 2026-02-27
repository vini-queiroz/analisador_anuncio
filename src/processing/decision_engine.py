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
      - tem_sim_lock: bool
      - tem_icloud_lock: bool
      - tem_config_lock: bool
      - versao_americana: bool (info)
      - menciona_nao_suporta_us_sim: bool (info)
    """
    reasons: List[str] = []

    # =========================================================
    # 0) BLOQUEIOS CRÍTICOS (hard reprova)
    # =========================================================
    if flags.get("tem_sim_lock") is True:
        reasons.append("Reprovado: SIM/operadora lock (有锁/卡贴机).")
        reasons.append(f"Tradução: {flags.get('sim_lock_status_pt')}")
        return DecisionResult(DECISION_VERSION_V1, "REPROVADO", reasons)

    if flags.get("tem_icloud_lock") is True:
        reasons.append("Reprovado: Apple ID/iCloud lock (risco de bloqueio).")
        reasons.append(f"Tradução: {flags.get('icloud_status_pt')}")
        return DecisionResult(DECISION_VERSION_V1, "REPROVADO", reasons)

    if flags.get("tem_config_lock") is True:
        reasons.append("Reprovado: Config/MDM lock.")
        reasons.append(f"Tradução: {flags.get('config_lock_status_pt')}")
        return DecisionResult(DECISION_VERSION_V1, "REPROVADO", reasons)

    # =========================================================
    # 1) INFOS (não bloqueiam)
    # =========================================================
    if flags.get("versao_americana") is True:
        reasons.append("Info: versão americana (美版/US). Penalidade leve ou nenhuma (política atual).")

    if flags.get("menciona_nao_suporta_us_sim") is True:
        reasons.append("Info: anúncio menciona que não suporta SIM dos EUA.")

    # =========================================================
    # 2) EXTRAÇÕES
    # =========================================================
    tem_tela = bool(flags.get("tem_problema_tela"))
    tem_desmont = bool(flags.get("tem_desmontagem"))

    bat = flags.get("bateria_percentual")
    try:
        bat_i: Optional[int] = int(bat) if bat is not None else None
    except Exception:
        bat_i = None

    versao = flags.get("versao")
    versao_ok = bool(versao and str(versao).strip())

    # =========================================================
    # 3) REPROVAÇÕES (hard)
    # =========================================================
    if tem_tela:
        reasons.append("Reprovado: problema de tela (tem_problema_tela=True).")
        return DecisionResult(DECISION_VERSION_V1, "REPROVADO", reasons)

    if bat_i is not None and bat_i < 80:
        reasons.append(f"Reprovado: bateria {bat_i}% (<80%).")
        return DecisionResult(DECISION_VERSION_V1, "REPROVADO", reasons)

    if tem_desmont and (bat_i is not None and bat_i < 85):
        reasons.append("Reprovado: indício de desmontagem + bateria abaixo de 85%.")
        return DecisionResult(DECISION_VERSION_V1, "REPROVADO", reasons)

    # =========================================================
    # 4) PENDÊNCIAS (não aprova sem info)
    # =========================================================
    pendencias: List[str] = []
    if bat_i is None:
        pendencias.append("Pendente: bateria não informada (não aprova automaticamente).")
    if not versao_ok:
        pendencias.append("Pendente: versão não informada (não aprova automaticamente).")

    if pendencias:
        # mantém infos + adiciona pendências
        reasons.extend(pendencias)
        return DecisionResult(DECISION_VERSION_V1, "PENDENTE", reasons)

    # =========================================================
    # 5) APROVADO
    # =========================================================
    reasons.append("Aprovado: passou nos critérios conservadores (sem tela, bateria ok, sem pendências).")
    return DecisionResult(DECISION_VERSION_V1, "APROVADO", reasons)
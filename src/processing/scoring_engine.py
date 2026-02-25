from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional


# -----------------------------
# CONFIG (POLÍTICA) — V1
# -----------------------------
SCORING_VERSION_V1 = "v1"

RULES_V1 = {
    # penalidades críticas
    "screen_issue_penalty": 40,      # tem_problema_tela
    "disassembly_penalty": 25,       # tem_desmontagem

    # bateria
    "battery_missing_penalty": 3,
    "battery_invalid_penalty": 3,
    "battery_lt_80_penalty": 20,
    "battery_80_84_penalty": 12,
    "battery_85_89_penalty": 6,

    # versão
    "version_missing_penalty": 2,
    "version_unknown_penalty": 2,
    "version_allowed": {"海外无锁", "国行", "港版", "日版"},

    # buckets
    "bucket_low_min": 85,     # >= 85  -> Baixo
    "bucket_mid_min": 65,     # >= 65  -> Médio, senão Alto
}


@dataclass(frozen=True)
class ScoreResult:
    scoring_version: str
    score: int
    risk_bucket: str
    reasons: List[str]


def _clamp_score(x: int) -> int:
    return 0 if x < 0 else 100 if x > 100 else x


def _risk_bucket(score: int, rules: Dict[str, Any]) -> str:
    if score >= int(rules["bucket_low_min"]):
        return "Baixo"
    if score >= int(rules["bucket_mid_min"]):
        return "Médio"
    return "Alto"


def score_ad_v1(flags: Dict[str, Any]) -> ScoreResult:
    """
    Scoring determinístico V1 (conservador).
    Entrada esperada em flags:
      - bateria_percentual: Optional[int]
      - tem_desmontagem: bool
      - tem_problema_tela: bool
      - versao: Optional[str]  (ex: 海外无锁 / 国行 / 港版)
    """
    rules = RULES_V1

    score = 100
    reasons: List[str] = []

    # --- TELA (crítico)
    tem_problema_tela = bool(flags.get("tem_problema_tela"))
    if tem_problema_tela:
        p = int(rules["screen_issue_penalty"])
        score -= p
        reasons.append(f"Tela com problema (flag tem_problema_tela): -{p}")

    # --- DESMONTAGEM (crítico)
    tem_desmontagem = bool(flags.get("tem_desmontagem"))
    if tem_desmontagem:
        p = int(rules["disassembly_penalty"])
        score -= p
        reasons.append(f"Indício de desmontagem/reparo (flag tem_desmontagem): -{p}")

    # --- BATERIA
    bat = flags.get("bateria_percentual")
    if bat is None:
        p = int(rules["battery_missing_penalty"])
        score -= p
        reasons.append(f"Bateria não informada: -{p}")
    else:
        try:
            bat_i = int(bat)
        except Exception:
            bat_i = None

        if bat_i is None:
            p = int(rules["battery_invalid_penalty"])
            score -= p
            reasons.append(f"Bateria inválida (não foi possível ler): -{p}")
        else:
            if bat_i < 80:
                p = int(rules["battery_lt_80_penalty"])
                score -= p
                reasons.append(f"Bateria {bat_i}% (<80%): -{p}")
            elif 80 <= bat_i <= 84:
                p = int(rules["battery_80_84_penalty"])
                score -= p
                reasons.append(f"Bateria {bat_i}% (80–84%): -{p}")
            elif 85 <= bat_i <= 89:
                p = int(rules["battery_85_89_penalty"])
                score -= p
                reasons.append(f"Bateria {bat_i}% (85–89%): -{p}")
            else:
                reasons.append(f"Bateria {bat_i}% (>=90%): 0")

    # --- VERSÃO
    versao = flags.get("versao")
    if not versao or str(versao).strip() == "":
        p = int(rules["version_missing_penalty"])
        score -= p
        reasons.append(f"Versão não informada: -{p}")
    else:
        v = str(versao).strip()
        allowed = set(rules["version_allowed"])
        if v in allowed:
            reasons.append(f"Versão {v}: 0")
        else:
            p = int(rules["version_unknown_penalty"])
            score -= p
            reasons.append(f"Versão desconhecida ({v}): -{p}")

    score = _clamp_score(score)
    bucket = _risk_bucket(score, rules)

    return ScoreResult(
        scoring_version=SCORING_VERSION_V1,
        score=score,
        risk_bucket=bucket,
        reasons=reasons,
    )
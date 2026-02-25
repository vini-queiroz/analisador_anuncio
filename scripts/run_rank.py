import argparse
import json
from pathlib import Path
from typing import Any, Dict, List

from src.processing.normalizer import normalize_model_fields, extract_commercial_flags, normalize_price
from src.processing.scoring_engine import score_ad_v1
from src.processing.decision_engine import decide_ad_v1


def load_jsonl(path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def save_jsonl(rows: List[Dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def main():
    parser = argparse.ArgumentParser(description="Normaliza + aplica scoring V1 + decisão + gera ranking em JSONL")
    parser.add_argument("--input", required=True, help="Caminho do JSONL de entrada (data/raw/...)")
    parser.add_argument("--output", default="data/processed/anuncios_ranked_v1.jsonl", help="Saída JSONL")
    args = parser.parse_args()

    in_path = Path(args.input)
    out_path = Path(args.output)

    ads = load_jsonl(in_path)

    enriched: List[Dict[str, Any]] = []
    for ad in ads:
        title = ad.get("titulo")
        desc = ad.get("descricao")

        # Normalização (modelo/memória/versão etc)
        norm = normalize_model_fields(title=title, desc=desc)

        # Flags comerciais (bateria/tela/desmontagem etc)
        flags = extract_commercial_flags(desc)

        # IMPORTANT: scoring/decisão usam "versao" como flag (vindo do normalizer)
        flags["versao"] = norm.get("versao")

        # Preço normalizado (caso seu JSONL traga string/int)
        price_raw = ad.get("preco")
        price_int = normalize_price(str(price_raw)) if price_raw is not None else None

        # Score + decisão
        result = score_ad_v1(flags)
        decision = decide_ad_v1(flags)

        # ✅ Agora cria o dicionário de saída ANTES de usar
        out = dict(ad)

        # Campos consolidados
        out["preco"] = price_int
        out.update(norm)
        out.update(flags)

        # Scoring
        out["scoring_version"] = result.scoring_version
        out["score_final"] = result.score
        out["risk_bucket"] = result.risk_bucket
        out["reasons"] = result.reasons

        # Decisão (APROVADO/REPROVADO/PENDENTE)
        out["decision_version"] = decision.decision_version
        out["status_decisao"] = decision.status_decisao
        out["decision_reasons"] = decision.decision_reasons

        enriched.append(out)

    # Ranking determinístico:
    # (opcional) prioridade por status: APROVADO > PENDENTE > REPROVADO
    status_rank = {"APROVADO": 2, "PENDENTE": 1, "REPROVADO": 0}

    def bat_key(x: Dict[str, Any]) -> int:
        b = x.get("bateria_percentual")
        return int(b) if isinstance(b, int) else -1

    enriched.sort(
        key=lambda x: (
            status_rank.get(x.get("status_decisao", "PENDENTE"), 1),
            int(x.get("score_final") or 0),
            bat_key(x),
            0 if not x.get("tem_problema_tela") else -1,
            0 if not x.get("tem_desmontagem") else -1,
            str(x.get("anuncio_id") or ""),
            str(x.get("url_anuncio") or ""),
        ),
        reverse=True,
    )

    save_jsonl(enriched, out_path)
    print("OK - Ranking gerado em:", out_path.resolve())


if __name__ == "__main__":
    main()
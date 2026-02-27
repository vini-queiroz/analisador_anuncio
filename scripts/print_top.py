import argparse
import json
from pathlib import Path
from typing import Any, Dict, List


def load_jsonl(path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def safe_str(v: Any) -> str:
    return "" if v is None else str(v)


def shorten(text: str, max_len: int = 140) -> str:
    t = (text or "").strip()
    if len(t) <= max_len:
        return t
    return t[: max_len - 1] + "…"


def bat_key(x: Dict[str, Any]) -> int:
    b = x.get("bateria_percentual")
    return int(b) if isinstance(b, int) else -1


def main():
    parser = argparse.ArgumentParser(
        description="Imprime Top N do JSONL rankeado (com dedupe por anuncio_id), incluindo status APROVADO/PENDENTE/REPROVADO."
    )
    parser.add_argument(
        "--input",
        default="data/processed/anuncios_ranked_v1.jsonl",
        help="Caminho do JSONL rankeado (default: data/processed/anuncios_ranked_v1.jsonl)",
    )
    parser.add_argument("--top", type=int, default=10, help="Quantidade de itens para imprimir (default: 10)")

    parser.add_argument("--show-reasons", action="store_true", help="Mostra reasons completos do scoring")
    parser.add_argument("--show-decision", action="store_true", help="Mostra decision_reasons completos (gates)")
    parser.add_argument("--show-desc", action="store_true", help="Mostra um trecho da descricao")
    parser.add_argument("--only-finance-ok", action="store_true", help="Mostra apenas anúncios com finance_ok=true")
    args = parser.parse_args()

    in_path = Path(args.input)
    rows = load_jsonl(in_path)

    # --- Deduplicação por anuncio_id (mantém maior score, desempate por bateria)
    unique: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        key = safe_str(r.get("anuncio_id") or r.get("url_anuncio"))
        if not key:
            continue
        if key not in unique:
            unique[key] = r
        else:
            cur = unique[key]
            s_new = int(r.get("score_final") or 0)
            s_cur = int(cur.get("score_final") or 0)
            if (s_new > s_cur) or (s_new == s_cur and bat_key(r) > bat_key(cur)):
                unique[key] = r

    ranked = list(unique.values())

    if args.only_finance_ok:
        ranked = [r for r in ranked if r.get("finance_ok") is True]

    # --- Ordenação (prioriza status, depois score)
    status_rank = {"APROVADO": 2, "PENDENTE": 1, "REPROVADO": 0}
    ranked.sort(
        key=lambda x: (
            status_rank.get(x.get("status_decisao", "PENDENTE"), 1),
            int(x.get("score_final") or 0),
            bat_key(x),
            0 if not x.get("tem_problema_tela") else -1,
            0 if not x.get("tem_desmontagem") else -1,
            safe_str(x.get("anuncio_id")),
            safe_str(x.get("url_anuncio")),
        ),
        reverse=True,
    )

    top_n = max(1, args.top)
    print(f"\n=== TOP {top_n} (dedupe: {len(rows)} -> {len(ranked)}) ===\n")

    for i, r in enumerate(ranked[:top_n], start=1):
        modelo = safe_str(r.get("modelo"))
        mem = safe_str(r.get("memoria_interna"))
        versao = safe_str(r.get("versao"))
        bat = r.get("bateria_percentual")
        bat_s = f"{bat}%" if isinstance(bat, int) else "N/I"

        score = int(r.get("score_final") or 0)
        bucket = safe_str(r.get("risk_bucket"))
        scoring_ver = safe_str(r.get("scoring_version") or "")

        status = safe_str(r.get("status_decisao") or "PENDENTE")
        decision_ver = safe_str(r.get("decision_version") or "")

        url = safe_str(r.get("url_anuncio"))

        print(f"{i:02d}. [{status}] SCORE {score} ({bucket}) {('('+scoring_ver+')') if scoring_ver else ''}")
        print(f"    {modelo} | {mem} | {versao} | Bateria: {bat_s}")
        if decision_ver:
            print(f"    Decision version: {decision_ver}")
        print(f"    URL: {url}")

        # --- decisão (gates)
        d_reasons = r.get("decision_reasons") or []
        if not isinstance(d_reasons, list):
            d_reasons = [safe_str(d_reasons)]

        if args.show_decision:
            for dr in d_reasons:
                print(f"    [DECISION] - {safe_str(dr)}")
        else:
            for dr in d_reasons[:2]:
                print(f"    [DECISION] - {shorten(safe_str(dr), 120)}")
            if len(d_reasons) > 2:
                print(f"    [DECISION] - (+{len(d_reasons) - 2} motivos)")

        # --- scoring reasons
        s_reasons = r.get("reasons") or []
        if not isinstance(s_reasons, list):
            s_reasons = [safe_str(s_reasons)]

        if args.show_reasons:
            for sr in s_reasons:
                print(f"    [SCORING] - {safe_str(sr)}")
        else:
            for sr in s_reasons[:3]:
                print(f"    [SCORING] - {shorten(safe_str(sr), 120)}")
            if len(s_reasons) > 3:
                print(f"    [SCORING] - (+{len(s_reasons) - 3} reasons)")

        if args.show_desc:
            desc = safe_str(r.get("descricao"))
            if desc:
                print(f"    DESC: {shorten(desc, 220)}")

        # ===============================
        # BLOCO FINANCEIRO
        # ===============================

        finance_ok = r.get("finance_ok")

        if finance_ok:
            preco_compra = r.get("preco_compra_brl")
            preco_revenda = r.get("preco_revenda_brl")
            custo_total = r.get("custo_total_brl")
            lucro = r.get("lucro_previsto_brl")
            margem = r.get("margem_prevista_pct")

            print(f"    💰 Compra (BRL): {preco_compra}")
            print(f"    🏷 Revenda (BRL): {preco_revenda}")
            print(f"    📦 Custo total: {custo_total}")
            print(f"    💵 Lucro previsto: {lucro}")
            print(f"    📈 Margem prevista: {margem}%")
        else:
            print("    ⚠ Financeiro: cálculo indisponível")
            reasons = r.get("finance_reasons") or []
            for fr in reasons:
                print(f"    [FINANCE] - {fr}")

        print()

    print("Dicas:")
    print("  Mostrar reasons completos:   python -m scripts.print_top --show-reasons")
    print("  Mostrar decision completos:  python -m scripts.print_top --show-decision")
    print("  Mostrar descrição:           python -m scripts.print_top --show-desc\n")


if __name__ == "__main__":
    main()
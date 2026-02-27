import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Tuple, Any
import re



@dataclass(frozen=True)
class FinanceConfig:
    fx_cny_brl: float
    frete_brl: float
    imposto_modo: str          # "percentual" ou "fixo"
    imposto_aliquota: float    # ex: 0.20
    imposto_fixo_brl: float    # ex: 200


def load_finance_config(path: Path) -> FinanceConfig:
    data = json.loads(path.read_text(encoding="utf-8"))
    imposto = data.get("imposto", {})
    return FinanceConfig(
        fx_cny_brl=float(data["fx_cny_brl"]),
        frete_brl=float(data["frete_brl"]),
        imposto_modo=str(imposto.get("modo", "percentual")).strip().lower(),
        imposto_aliquota=float(imposto.get("aliquota", 0.0)),
        imposto_fixo_brl=float(imposto.get("fixo_brl", 0.0)),
    )


_RE_SPACES = re.compile(r"\s+")

def _norm_key(s: str) -> str:
    # remove espaços múltiplos e espaços “invisíveis”
    s = (s or "").replace("\u00A0", " ").strip()   # NBSP -> space
    s = _RE_SPACES.sub(" ", s)
    return s

def _norm_mem(s: str) -> str:
    s = _norm_key(s).upper().replace(" ", "")
    return s

def load_resale_table_csv(path: Path) -> Dict[Tuple[str, str], float]:
    """
    Lê CSV de revenda de forma robusta (inclui BOM).
    Chave: (modelo, memoria_interna) -> preco_revenda_brl
    """
    table: Dict[Tuple[str, str], float] = {}

    # utf-8-sig remove BOM automaticamente
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        # detectar delimitador: ',' ou ';'
        sample = f.read(2048)
        f.seek(0)
        delimiter = ";" if sample.count(";") > sample.count(",") else ","

        reader = csv.DictReader(f, delimiter=delimiter)
        for row in reader:
            modelo = _norm_key(row.get("modelo", ""))
            mem = _norm_mem(row.get("memoria_interna", ""))
            preco_raw = (row.get("preco_revenda_brl") or "").strip()

            if not modelo or not mem or not preco_raw:
                continue

            # aceita "8.400", "8,400", "8400", "R$ 8.400"
            preco_clean = (
                preco_raw.replace("R$", "")
                .replace(".", "")     # remove separador de milhar
                .replace(",", ".")    # decimal pt -> en
                .strip()
            )
            try:
                preco = float(preco_clean)
            except ValueError:
                continue

            table[(modelo, mem)] = preco

    return table

def lookup_resale_price(table: Dict[Tuple[str, str], float], modelo: str, memoria_interna: str) -> Optional[float]:
    return table.get((_norm_key(modelo), _norm_mem(memoria_interna)))

def compute_financials(
    preco_compra_cny: Optional[int],
    modelo: Optional[str],
    memoria_interna: Optional[str],
    resale_table: Dict[Tuple[str, str, str], float],
    cfg: FinanceConfig,
) -> Dict[str, Any]:
    """
    Retorna campos financeiros determinísticos.
    NÃO toma decisão. Só calcula.
    """
    out: Dict[str, Any] = {
        "fx_cny_brl": cfg.fx_cny_brl,
        "frete_brl": cfg.frete_brl,
        "imposto_modo": cfg.imposto_modo,
        "imposto_aliquota": cfg.imposto_aliquota if cfg.imposto_modo == "percentual" else None,
        "imposto_fixo_brl": cfg.imposto_fixo_brl if cfg.imposto_modo == "fixo" else None,
    }

    if preco_compra_cny is None or not modelo or not memoria_interna:
        out["finance_ok"] = False
        out["finance_reasons"] = ["Sem dados mínimos para cálculo financeiro (preço/modelo/memória)."]
        return out

    preco_compra_brl = round(preco_compra_cny * cfg.fx_cny_brl, 2)
    preco_revenda_brl = lookup_resale_price(resale_table, modelo, memoria_interna)

    out["preco_compra_cny"] = preco_compra_cny
    out["preco_compra_brl"] = preco_compra_brl
    out["preco_revenda_brl"] = preco_revenda_brl

    if preco_revenda_brl is None:
        out["finance_ok"] = False
        out["finance_reasons"] = ["Preço de revenda não encontrado na tabela (modelo/memória/versão)."]
        return out

    base_imposto = preco_compra_brl + cfg.frete_brl

    if cfg.imposto_modo == "fixo":
        imposto_brl = round(cfg.imposto_fixo_brl, 2)
    else:
        imposto_brl = round(cfg.imposto_aliquota * base_imposto, 2)

    custo_total_brl = round(preco_compra_brl + cfg.frete_brl + imposto_brl, 2)
    lucro_previsto_brl = round(preco_revenda_brl - custo_total_brl, 2)

    # margem % em cima do custo total (mais conservador)
    margem_prevista_pct = round((lucro_previsto_brl / custo_total_brl) * 100, 2) if custo_total_brl > 0 else None

    out.update({
        "imposto_brl": imposto_brl,
        "custo_total_brl": custo_total_brl,
        "lucro_previsto_brl": lucro_previsto_brl,
        "margem_prevista_pct": margem_prevista_pct,
        "finance_ok": True,
        "finance_reasons": [],
    })
    return out
import json
from collections import Counter
from pathlib import Path

from src.processing.normalizer import normalize_model_fields, normalize_price

# se você tiver essa função no normalizer, descomente:
# from src.processing.normalizer import extract_commercial_flags

INPUT = Path("data/raw/anuncios_xianyu_vendor_20260225_174900.jsonl")

def pct(a, b):
    return 0 if b == 0 else round(100 * a / b, 1)

def main():
    n = 0
    ok_price = 0
    ok_model = 0
    ok_storage = 0
    ok_version = 0

    model_counter = Counter()
    storage_counter = Counter()
    version_counter = Counter()

    sample_bad = []

    with INPUT.open("r", encoding="utf-8") as f:
        for line in f:
            ad = json.loads(line)
            n += 1

            title = ad.get("titulo")
            desc = ad.get("descricao")

            # preço (aceita vir int ou str no arquivo)
            price_raw = ad.get("preco")
            price_norm = normalize_price(str(price_raw)) if price_raw is not None else None
            if isinstance(price_norm, int) or price_norm is None:
                ok_price += 1

            norm = normalize_model_fields(title=title, desc=desc)

            modelo = norm.get("modelo")
            versao = norm.get("versao")
            storage = norm.get("memoria_interna")

            if modelo:
                ok_model += 1
                model_counter[modelo] += 1
            else:
                sample_bad.append(("SEM_MODELO", ad.get("url_anuncio")))

            if storage:
                ok_storage += 1
                storage_counter[storage] += 1

            if versao:
                ok_version += 1
                version_counter[versao] += 1

            # flags (se você tiver no normalizer)
            # flags = extract_commercial_flags(desc)
            # ...

    print("=== CHECK NORMALIZER ===")
    print("Arquivo:", INPUT)
    print("Total anúncios:", n)
    print(f"Preço OK (tipo int/None): {ok_price}/{n} ({pct(ok_price,n)}%)")
    print(f"Modelo extraído: {ok_model}/{n} ({pct(ok_model,n)}%)")
    print(f"Memória extraída: {ok_storage}/{n} ({pct(ok_storage,n)}%)")
    print(f"Versão extraída: {ok_version}/{n} ({pct(ok_version,n)}%)")

    print("\nTop modelos:")
    for m, c in model_counter.most_common(10):
        print(f"  {m}: {c}")

    print("\nTop memórias:")
    for m, c in storage_counter.most_common(10):
        print(f"  {m}: {c}")

    print("\nTop versões:")
    for v, c in version_counter.most_common(10):
        print(f"  {v}: {c}")

    if sample_bad:
        print("\nExemplos com problema (primeiros 10):")
        for tag, url in sample_bad[:10]:
            print(" ", tag, url)

if __name__ == "__main__":
    main()
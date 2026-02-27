from pathlib import Path
from src.processing.finance_engine import load_resale_table_csv, lookup_resale_price

table = load_resale_table_csv(Path("data/config/precos_revenda.csv"))
print("Total de chaves carregadas:", len(table))

# teste manual (ajuste para um caso que você sabe que existe no CSV)
modelo = "iPhone 17 Pro Max"
mem = "1TB"
print("Lookup:", modelo, mem, "=>", lookup_resale_price(table, modelo, mem))

# imprime 5 chaves pra inspecionar
print("\nAmostra de chaves:")
for i, k in enumerate(list(table.keys())[:5], start=1):
    print(i, k, "=>", table[k])
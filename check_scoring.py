from src.processing.scoring_engine import score_ad_v1

def assert_contains(reasons, needle: str):
    if not any(needle in r for r in reasons):
        raise AssertionError(f"Expected reasons to contain '{needle}', got: {reasons}")

def run_case(name: str, flags: dict, expected_score: int, expected_bucket: str, must_contain: list[str]):
    res = score_ad_v1(flags)
    if res.score != expected_score:
        raise AssertionError(f"[{name}] score {res.score} != expected {expected_score}. reasons={res.reasons}")
    if res.risk_bucket != expected_bucket:
        raise AssertionError(f"[{name}] bucket {res.risk_bucket} != expected {expected_bucket}. reasons={res.reasons}")
    for s in must_contain:
        assert_contains(res.reasons, s)

def main():
    cases = [
        # 1) perfeito (bateria alta, sem flags críticas, versao ok)
        dict(
            name="perfect_95_overseas",
            flags={"bateria_percentual": 95, "tem_desmontagem": False, "tem_problema_tela": False, "versao": "海外无锁"},
            expected_score=100,
            expected_bucket="Baixo",
            must_contain=["Bateria 95% (>=90%): 0", "Versão 海外无锁: 0"],
        ),

        # 2) bateria 82% (penalidade 12)
        dict(
            name="battery_82",
            flags={"bateria_percentual": 82, "tem_desmontagem": False, "tem_problema_tela": False, "versao": "海外无锁"},
            expected_score=88,
            expected_bucket="Baixo",
            must_contain=["Bateria 82% (80–84%): -12"],
        ),

        # 3) bateria não informada (-3)
        dict(
            name="battery_missing",
            flags={"bateria_percentual": None, "tem_desmontagem": False, "tem_problema_tela": False, "versao": "海外无锁"},
            expected_score=97,
            expected_bucket="Baixo",
            must_contain=["Bateria não informada: -3"],
        ),

        # 4) tela com problema (-40) e bateria 82 (-12) => 48 (Alto)
        dict(
            name="screen_issue_and_battery_82",
            flags={"bateria_percentual": 82, "tem_desmontagem": False, "tem_problema_tela": True, "versao": "海外无锁"},
            expected_score=48,
            expected_bucket="Alto",
            must_contain=["Tela com problema (flag tem_problema_tela): -40", "Bateria 82% (80–84%): -12"],
        ),

        # 5) desmontagem (-25) e bateria 79 (-20) => 55 (Alto)
        dict(
            name="disassembly_and_battery_79",
            flags={"bateria_percentual": 79, "tem_desmontagem": True, "tem_problema_tela": False, "versao": "海外无锁"},
            expected_score=55,
            expected_bucket="Alto",
            must_contain=["Indício de desmontagem/reparo (flag tem_desmontagem): -25", "Bateria 79% (<80%): -20"],
        ),

        # 6) versão ausente (-2) + bateria ausente (-3) => 95
        dict(
            name="version_missing_battery_missing",
            flags={"bateria_percentual": None, "tem_desmontagem": False, "tem_problema_tela": False, "versao": None},
            expected_score=95,
            expected_bucket="Baixo",
            must_contain=["Versão não informada: -2", "Bateria não informada: -3"],
        ),

        # 7) versão desconhecida (-2) + bateria 85–89 (-6) => 92
        dict(
            name="unknown_version_battery_88",
            flags={"bateria_percentual": 88, "tem_desmontagem": False, "tem_problema_tela": False, "versao": "XYZ"},
            expected_score=92,
            expected_bucket="Baixo",
            must_contain=["Versão desconhecida (XYZ): -2", "Bateria 88% (85–89%): -6"],
        ),

        # 8) bateria inválida (string ruim) deve cair como -3
        dict(
            name="battery_invalid",
            flags={"bateria_percentual": "abc", "tem_desmontagem": False, "tem_problema_tela": False, "versao": "海外无锁"},
            expected_score=97,
            expected_bucket="Baixo",
            must_contain=["Bateria inválida (não foi possível ler): -3"],
        ),
    ]

    for c in cases:
        run_case(**c)

    print("OK - check_scoring.py passou em todos os casos.")

if __name__ == "__main__":
    main()
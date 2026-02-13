import argparse
import json
import random
import re
import time
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Set, Tuple

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

RE_ID = re.compile(r"[?&]id=(\d+)")
RE_SPACES = re.compile(r"\s+")
RE_PRICE = re.compile(r"[¥￥]\s*([0-9]{1,6}(?:[.,][0-9]{1,2})?)")
RE_PRICE_FALLBACK = re.compile(r"\b([0-9]{2,6})\b")
RE_IPHONE = re.compile(r"(?:iphone|苹果)\s*([0-9]{2})")
RE_STORAGE_G = re.compile(r"\b(128|256|512)\s*g\b")
RE_STORAGE_TB = re.compile(r"\b(1)\s*tb\b")
RE_LABEL_MODELO = re.compile(r"(型\s*号|型号)\s*[:：]\s*(.+?)(?=\s*(品\s*牌|存\s*储|运\s*行|版\s*本|成\s*色|$))")
RE_LABEL_STORAGE = re.compile(r"(存\s*储\s*容\s*量|存储容量)\s*[:：]\s*(.+?)(?=\s*(运\s*行|版\s*本|成\s*色|$))")
RE_LABEL_RAM = re.compile(r"(运\s*行\s*内\s*存|运行内存)\s*[:：]\s*(.+?)(?=\s*(版\s*本|成\s*色|$))")
RE_LABEL_VERSION = re.compile(r"(版\s*本|版本)\s*[:：]\s*(.+?)(?=\s*(成\s*色|$))")



@dataclass
class XianyuAd:
    anuncio_id: Optional[str]
    modelo: Optional[str]            # extraído da descrição (prioridade)
    versao: Optional[str]            # ex: 海外无锁 / 国行 / 港版
    memoria_interna: Optional[str]   # ex: 256GB, 1TB
    memoria_ram: Optional[str]       # ex: 6GB, 8GB
    titulo: Optional[str]
    preco: Optional[str]
    descricao: Optional[str]
    vendedor: Optional[str]
    origem_anuncio: str
    url_anuncio: str


def _ensure_dirs() -> None:
    Path("data/raw").mkdir(parents=True, exist_ok=True)


def _save_jsonl(rows: List[dict], out_path: Path) -> None:
    with out_path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def _extract_id_from_url(url: str) -> Optional[str]:
    m = RE_ID.search(url)
    return m.group(1) if m else None


def _looks_like_generic_page(title: Optional[str], body_text: str) -> bool:
    if not title:
        return True

    t = title.strip()

    # título padrão do site quando não carregou
    if "闲鱼 - 闲不住？上闲鱼" in t:
        return True

    # só considera genérico se tiver rodapé E não tiver preço
    if (
        "增值电信业务经营许可证" in body_text
        and "¥" not in body_text
        and "￥" not in body_text
    ):
        return True

    return False



def _wait_for_item_content(page, timeout_ms: int = 7000) -> None:
    page.wait_for_function(
        """() => {
            const t = document.body ? document.body.innerText : "";
            return t.includes("¥") || t.includes("￥") || t.includes("机器简介");
        }""",
        timeout=timeout_ms
    )



def _extract_model_from_title(title: Optional[str]) -> Optional[str]:
    if not title:
        return None
    t = title.lower()

    m_phone = RE_IPHONE.search(t)
    if not m_phone:
        return None
    phone_num = m_phone.group(1)

    m_storage = RE_STORAGE_G.search(t) or RE_STORAGE_TB.search(t)
    if m_storage:
        if "tb" in m_storage.group(0):
            storage = "1TB"
        else:
            storage = f"{m_storage.group(1)}GB"
        return f"iPhone {phone_num} {storage}"

    return f"iPhone {phone_num}"


def _extract_price_from_page_text(text: str) -> Optional[str]:
    if not text:
        return None

    m = RE_PRICE.search(text)
    if m:
        return m.group(1).replace(",", "").strip()

    m2 = RE_PRICE_FALLBACK.search(text)
    if m2:
        return m2.group(1)

    return None

def _extract_specs_from_description(desc: Optional[str]):
    if not desc:
        return None, None, None, None

    modelo = None
    versao = None
    memoria_interna = None
    memoria_ram = None

    m = RE_LABEL_MODELO.search(desc)
    if m:
        modelo = RE_SPACES.sub(" ", m.group(2)).strip()

    m = RE_LABEL_STORAGE.search(desc)
    if m:
        memoria_interna = RE_SPACES.sub("", m.group(2)).upper().strip()

    m = RE_LABEL_RAM.search(desc)
    if m:
        memoria_ram = RE_SPACES.sub("", m.group(2)).upper().strip()

    m = RE_LABEL_VERSION.search(desc)
    if m:
        versao = RE_SPACES.sub(" ", m.group(2)).strip()

    return modelo, versao, memoria_interna, memoria_ram


def scrape_vendor_profile(
    profile_url: str,
    limit: int = 30,
    headless: bool = True,
    max_scrolls: int = 30,
) -> Tuple[List[XianyuAd], dict]:

    origem = "xianyu"
    collected: List[XianyuAd] = []
    seen_urls: Set[str] = set()
    debug = {"profile_url": profile_url, "found_item_urls": 0, "detail_success": 0, "detail_fail": 0}

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=headless,
            args=["--disable-blink-features=AutomationControlled"]
        )

        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 720},
            locale="zh-CN",
        )

        # ✅ BLOQUEIA RECURSOS PESADOS (GANHO GRANDE)
        def _route_handler(route, request):
            rt = request.resource_type
            if rt in ("image", "media", "font"):
                return route.abort()
            return route.continue_()

        context.route("**/*", _route_handler)

        # Uma página pro perfil + uma pro detalhe
        page = context.new_page()
        detail_page = context.new_page()

        # PERFIL
        page.goto(profile_url, wait_until="domcontentloaded")
        try:
            page.wait_for_load_state("load", timeout=12000)
        except PlaywrightTimeoutError:
            pass

        # scroll (mais rápido)
        last_height = 0
        for _ in range(max_scrolls):
            page.mouse.wheel(0, 2800)
            time.sleep(random.uniform(0.20, 0.45))
            try:
                height = page.evaluate("() => document.body.scrollHeight")
            except Exception:
                break
            if height == last_height:
                break
            last_height = height

        # coletar URLs
        item_urls: Set[str] = set()
        for a in page.query_selector_all("a[href]"):
            href = a.get_attribute("href") or ""
            if "/item" not in href:
                continue
            full = href if href.startswith("http") else "https://www.goofish.com" + href
            if "goofish.com/item" in full or "h5.m.goofish.com/item" in full:
                item_urls.add(full)

        debug["found_item_urls"] = len(item_urls)
        item_list = list(item_urls)[:limit]

        # DETALHES
        for url in item_list:
            if url in seen_urls:
                continue
            seen_urls.add(url)

            time.sleep(random.uniform(0.18, 0.55))

            try:
                ok = False
                last_title = None
                last_body = ""

                for attempt in range(2):  # ✅ retry 1x
                    detail_page.goto(url, wait_until="domcontentloaded")
                    try:
                        detail_page.wait_for_load_state("load", timeout=9000)
                    except PlaywrightTimeoutError:
                        pass

                    # espera sinais de conteúdo do item (sem CSS)
                    try:
                        _wait_for_item_content(detail_page, timeout_ms=9000)
                    except PlaywrightTimeoutError:
                        pass

                    # title
                    try:
                        last_title = detail_page.title()
                        last_title = RE_SPACES.sub(" ", last_title).strip() if last_title else None
                    except Exception:
                        last_title = None

                    # body
                    try:
                        last_body = detail_page.inner_text("body") or ""
                        last_body = RE_SPACES.sub(" ", last_body).strip()
                    except Exception:
                        last_body = ""

                    if not _looks_like_generic_page(last_title, last_body):
                        ok = True
                        break

                    time.sleep(random.uniform(0.35, 0.75))
                    try:
                        detail_page.reload(wait_until="domcontentloaded")
                    except Exception:
                        pass

                if not ok:
                    debug["detail_fail"] += 1
                    continue

                title = last_title
                body_text = last_body
                desc = None
                if body_text:

                    # 1️⃣ corta no bloco de recomendação
                    cut_markers = [
                        "为你推荐",
                        "推荐",
                        "猜你喜欢"
                    ]

                    clean_text = body_text
                    for marker in cut_markers:
                        idx = clean_text.find(marker)
                        if idx != -1:
                            clean_text = clean_text[:idx]
                            break

                    # 2️⃣ remove o prefixo inicial do site se existir
                    if "机器简介" in clean_text:
                        idx = clean_text.find("机器简介")
                        clean_text = clean_text[idx:]

                    # 3️⃣ limpeza final
                    clean_text = RE_SPACES.sub(" ", clean_text).strip()

                    desc = clean_text
                
                price = _extract_price_from_page_text(body_text)
                # 🔹 Extrai specs da descrição primeiro
                modelo_desc, versao, memoria_interna, memoria_ram = _extract_specs_from_description(desc)

                # 🔹 Se não encontrou modelo na descrição, usa título
                modelo = modelo_desc if modelo_desc else _extract_model_from_title(title)

                ad = XianyuAd(
                anuncio_id=_extract_id_from_url(url),
                modelo=modelo,
                versao=versao,
                memoria_interna=memoria_interna,
                memoria_ram=memoria_ram,
                titulo=title,
                preco=price,
                descricao=desc,
                vendedor=None,
                origem_anuncio=origem,
                url_anuncio=url,
                )



                collected.append(ad)
                debug["detail_success"] += 1

            except Exception as e:
                print(f"Erro ao processar {url}: {e}")
                debug["detail_fail"] += 1
                continue

        detail_page.close()
        page.close()
        context.close()
        browser.close()

    return collected, debug


def main():
    parser = argparse.ArgumentParser(description="Scraper simples do Xianyu (goofish.com) a partir da página do vendedor.")
    parser.add_argument(
        "--profile-url",
        required=True,
        help="URL do perfil do vendedor (ex: https://www.goofish.com/personal?userId=918690794)",
    )
    parser.add_argument("--limit", type=int, default=30, help="Quantidade máxima de anúncios")
    parser.add_argument("--headless", action="store_true", help="Rodar headless (sem abrir janela)")
    args = parser.parse_args()

    _ensure_dirs()

    ads, debug = scrape_vendor_profile(
        profile_url=args.profile_url,
        limit=args.limit,
        headless=args.headless,
    )

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = Path(f"data/raw/anuncios_xianyu_vendor_{ts}.jsonl")

    rows = [asdict(a) for a in ads]
    _save_jsonl(rows, out_path)

    print("=== Xianyu Scraper (SIMPLE) ===")
    print("Profile:", debug["profile_url"])
    print("Item URLs encontrados:", debug["found_item_urls"])
    print("Detalhes OK:", debug["detail_success"])
    print("Detalhes FAIL:", debug["detail_fail"])
    print("Arquivo gerado:", out_path.resolve())


if __name__ == "__main__":
    main()

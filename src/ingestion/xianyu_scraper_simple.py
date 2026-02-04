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


@dataclass
class XianyuAd:
    anuncio_id: Optional[str]
    modelo: Optional[str]          # agora é extraído do título
    titulo: Optional[str]
    preco: Optional[str]           # mantemos como string (ex: "899", "¥899", etc.) para não quebrar
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
    m = re.search(r"[?&]id=(\d+)", url)
    return m.group(1) if m else None


def _extract_model_from_title(title: Optional[str]) -> Optional[str]:
    """
    Heurística simples:
    - Procura por 'iphone' + número (13/14/15/16/17 etc.)
    - Procura por armazenamento (128g/256g/512g/1tb)
    Retorna algo como: "iPhone 16 128GB" (se achar)
    """
    if not title:
        return None

    t = title.lower()

    # iPhone número (ex: 苹果16 / iphone16 / iphone 16 / 16pro etc.)
    m_phone = re.search(r"(?:iphone|苹果)\s*([0-9]{2})", t)
    if not m_phone:
        return None
    phone_num = m_phone.group(1)

    # armazenamento
    m_storage = re.search(r"\b(128|256|512)\s*g\b", t) or re.search(r"\b(1)\s*tb\b", t)
    storage = None
    if m_storage:
        if "tb" in m_storage.group(0):
            storage = "1TB"
        else:
            storage = f"{m_storage.group(1)}GB"

    if storage:
        return f"iPhone {phone_num} {storage}"
    return f"iPhone {phone_num}"


def _extract_price_from_page_text(text: str) -> Optional[str]:
    """
    Extração simples de preço:
    - procura primeiro por ¥/￥ seguido de número
    - se não achar, procura por um número "isolado" plausível
    Retorna como string (ex: "899", "2799")
    """
    if not text:
        return None

    # 1) ¥ 899 / ￥899 / ¥899.00
    m = re.search(r"[¥￥]\s*([0-9]{1,6}(?:[.,][0-9]{1,2})?)", text)
    if m:
        return m.group(1).replace(",", "").strip()

    # 2) fallback: algum número plausível (evita capturar números enormes)
    m2 = re.search(r"\b([0-9]{2,6})\b", text)
    if m2:
        return m2.group(1)

    return None


def scrape_vendor_profile(
    profile_url: str,
    limit: int = 30,
    headless: bool = True,
    max_scrolls: int = 30,
) -> Tuple[List[XianyuAd], dict]:
    """
    MVP simples:
    1) Abre perfil do vendedor
    2) Rola a página para carregar itens
    3) Coleta URLs de itens
    4) Abre cada item e extrai: url, titulo, preco, descricao (texto do body)
    5) Extrai modelo do título
    """

    origem = "xianyu"
    collected: List[XianyuAd] = []
    seen_urls: Set[str] = set()
    debug = {"profile_url": profile_url, "found_item_urls": 0, "detail_success": 0, "detail_fail": 0}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        )
        page = context.new_page()

        page.goto(profile_url, wait_until="domcontentloaded")
        try:
            page.wait_for_load_state("networkidle", timeout=15000)
        except PlaywrightTimeoutError:
            pass

        # scroll para carregar
        last_height = 0
        for _ in range(max_scrolls):
            page.mouse.wheel(0, 2000)
            time.sleep(random.uniform(0.7, 1.3))
            try:
                page.wait_for_load_state("networkidle", timeout=6000)
            except PlaywrightTimeoutError:
                pass

            height = page.evaluate("() => document.body.scrollHeight")
            if height == last_height:
                break
            last_height = height

        # coletar URLs dos itens
        item_urls: Set[str] = set()
        for a in page.query_selector_all("a[href]"):
            href = a.get_attribute("href") or ""
            if "/item" not in href:
                continue
            full = href if href.startswith("http") else "https://www.goofish.com" + href
            if "goofish.com/item" in full or "h5.m.goofish.com/item" in full:
                item_urls.add(full)

        debug["found_item_urls"] = len(item_urls)

        # limita
        item_list = list(item_urls)[:limit]

        for url in item_list:
            if url in seen_urls:
                continue
            seen_urls.add(url)

            time.sleep(random.uniform(0.8, 1.6))

            dpage = context.new_page()
            try:
                dpage.goto(url, wait_until="domcontentloaded")
                try:
                    dpage.wait_for_load_state("networkidle", timeout=12000)
                except PlaywrightTimeoutError:
                    pass

                # título: tenta <title> (funciona bem no MVP)
                html = dpage.content()
                title = None
                mt = re.search(r"<title>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
                if mt:
                    title = re.sub(r"\s+", " ", mt.group(1)).strip()

                # texto do body: melhor para descrição no MVP (evita CSS do HTML bruto)
                body_text = dpage.inner_text("body")
                body_text = re.sub(r"\s+", " ", body_text).strip() if body_text else ""
                desc = body_text[:1000] if body_text else None  # recorte MVP

                # preço: extração simples a partir do texto do body
                price = _extract_price_from_page_text(body_text)

                # modelo vem do título
                modelo = _extract_model_from_title(title)

                ad = XianyuAd(
                    anuncio_id=_extract_id_from_url(url),
                    modelo=modelo,
                    titulo=title,
                    preco=price,
                    descricao=desc,
                    vendedor=None,  # MVP: depois extraímos via JSON
                    origem_anuncio=origem,
                    url_anuncio=url,
                )
                collected.append(ad)
                debug["detail_success"] += 1
            except Exception:
                debug["detail_fail"] += 1
            finally:
                dpage.close()

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

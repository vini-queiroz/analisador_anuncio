import argparse
import json
import random
import re
import time
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Set, Tuple

from src.processing.normalizer import normalize_price
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

RE_ID = re.compile(r"[?&]id=(\d+)")
RE_SPACES = re.compile(r"\s+")
RE_PRICE = re.compile(r"[¥￥]\s*([0-9]{1,6}(?:[.,][0-9]{1,2})?)")
RE_PRICE_FALLBACK = re.compile(r"\b([0-9]{2,6})\b")
RE_IPHONE = re.compile(r"(?:iphone|苹果)\s*([0-9]{2})", re.I)
RE_STORAGE_G = re.compile(r"\b(128|256|512)\s*g\b", re.I)
RE_STORAGE_TB = re.compile(r"\b(1)\s*tb\b", re.I)

RE_LABEL_MODELO = re.compile(r"(型\s*号|型号)\s*[:：]\s*(.+?)(?=\s*(品\s*牌|存\s*储|运\s*行|版\s*本|成\s*色|$))")
RE_LABEL_STORAGE = re.compile(r"(存\s*储\s*容\s*量|存储容量)\s*[:：]\s*(.+?)(?=\s*(运\s*行|版\s*本|成\s*色|$))")
RE_LABEL_RAM = re.compile(r"(运\s*行\s*内\s*存|运行内存)\s*[:：]\s*(.+?)(?=\s*(版\s*本|成\s*色|$))")
RE_LABEL_VERSION = re.compile(r"(版\s*本|版本)\s*[:：]\s*(.+?)(?=\s*(成\s*色|$))")

RE_ITEM_URL_ABS = re.compile(r"https?://www\.goofish\.com/item\?id=\d+")
RE_ITEM_URL_REL = re.compile(r"(/item\?id=\d+)")

DESC_START_MARKERS = ["机器简介", "宝贝描述", "商品描述", "苹果", "iPhone"]
DESC_END_MARKERS = ["聊一聊", "立即购买", "收藏", "进入店铺", "为你推荐", "猜你喜欢", "推荐"]

@dataclass
class XianyuAd:
    anuncio_id: Optional[str]
    modelo: Optional[str]
    versao: Optional[str]
    memoria_interna: Optional[str]
    memoria_ram: Optional[str]
    titulo: Optional[str]
    preco: Optional[int]
    descricao: Optional[str]
    vendedor: Optional[str]
    origem_anuncio: str
    url_anuncio: str


def _ensure_dirs() -> None:
    Path("data/raw").mkdir(parents=True, exist_ok=True)
    Path("data/debug").mkdir(parents=True, exist_ok=True)
    Path("data/pw_user").mkdir(parents=True, exist_ok=True)


def _save_jsonl(rows: List[dict], out_path: Path) -> None:
    with out_path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def _extract_id_from_url(url: str) -> Optional[str]:
    m = RE_ID.search(url)
    return m.group(1) if m else None


def _fast_clean_text(t: str) -> str:
    return RE_SPACES.sub(" ", (t or "")).strip()


def _extract_real_desc_from_body(body_text: str) -> Optional[str]:
    t = _fast_clean_text(body_text)
    if not t:
        return None

    # corte frequente do cabeçalho/política antes do texto real
    if "承担" in t:
        t = t.split("承担", 1)[1].strip()

    # início
    start_idx = None
    for m in DESC_START_MARKERS:
        idx = t.find(m)
        if idx != -1 and (start_idx is None or idx < start_idx):
            start_idx = idx
    if start_idx is not None:
        t = t[start_idx:].strip()

    # fim
    end_idx = None
    for m in DESC_END_MARKERS:
        idx = t.find(m)
        if idx != -1 and (end_idx is None or idx < end_idx):
            end_idx = idx
    if end_idx is not None:
        t = t[:end_idx].strip()

    if len(t) > 1800:
        t = t[:1800].strip()

    return t or None


def _looks_like_generic_page(title: Optional[str], body_text: str) -> bool:
    if not title:
        return True
    t = title.strip()
    if "闲鱼 - 闲不住？上闲鱼" in t:
        return True
    if ("增值电信业务经营许可证" in body_text and "¥" not in body_text and "￥" not in body_text):
        return True
    return False


def _wait_for_item_content(page, timeout_ms: int = 7000) -> None:
    page.wait_for_function(
        """() => {
            const t = document.body ? document.body.innerText : "";
            return t.includes("¥") || t.includes("￥") || t.includes("机器简介") || t.includes("宝贝描述") || t.includes("商品描述");
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
        if "tb" in m_storage.group(0).lower():
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

    modelo = versao = memoria_interna = memoria_ram = None

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


def _collect_item_urls_from_profile(page) -> Set[str]:
    urls: Set[str] = set()

    # DOM
    try:
        for a in page.query_selector_all("a[href]"):
            href = a.get_attribute("href") or ""
            if "id=" not in href:
                continue
            if "/item" in href or "goofish.com/item" in href:
                full = href if href.startswith("http") else "https://www.goofish.com" + href
                if "goofish.com/item" in full and "id=" in full:
                    urls.add(full)
    except Exception:
        pass

    # HTML regex fallback
    try:
        html = page.content()
        for u in RE_ITEM_URL_ABS.findall(html):
            urls.add(u)
        for rel in RE_ITEM_URL_REL.findall(html):
            urls.add("https://www.goofish.com" + rel)
    except Exception:
        pass

    return urls


def _debug_dump(page, prefix: str) -> None:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    png = Path(f"data/debug/{prefix}_{ts}.png")
    html = Path(f"data/debug/{prefix}_{ts}.html")
    try:
        page.screenshot(path=str(png), full_page=True)
    except Exception:
        pass
    try:
        html.write_text(page.content(), encoding="utf-8")
    except Exception:
        pass

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

    user_data_dir = str(Path("data/pw_user").resolve())

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=user_data_dir,
            headless=headless,
            args=["--disable-blink-features=AutomationControlled"],
            locale="zh-CN",
            viewport={"width": 1280, "height": 800},
        )

        def _route_handler(route, request):
            if request.resource_type in ("image", "media", "font"):
                return route.abort()
            return route.continue_()

        context.route("**/*", _route_handler)

        page = context.new_page()
        detail_page = context.new_page()

        # PERFIL
        page.goto(profile_url, wait_until="domcontentloaded", timeout=30000)

        # espera até aparecer pelo menos 1 link de item (sem ENTER)
        try:
            page.wait_for_function(
                """() => {
                    const html = document.documentElement.innerHTML;
                    return html.includes("/item?id=");
                }""",
                timeout=15000
            )
        except PlaywrightTimeoutError:
            pass

        # scroll automático
        last_height = 0
        for _ in range(max_scrolls):
            page.mouse.wheel(0, 3000)
            time.sleep(random.uniform(0.08, 0.15))
            try:
                height = page.evaluate("() => document.body.scrollHeight")
            except Exception:
                break
            if height == last_height:
                break
            last_height = height

        item_urls = _collect_item_urls_from_profile(page)
        debug["found_item_urls"] = len(item_urls)

        if debug["found_item_urls"] == 0:
            print("⚠️ Nenhum item encontrado. Possível bloqueio ou perfil vazio.")
            detail_page.close()
            page.close()
            context.close()
            return collected, debug

        item_list = list(item_urls)[:limit]

        # DETALHES
        for url in item_list:
            if url in seen_urls:
                continue
            seen_urls.add(url)

            time.sleep(random.uniform(0.05, 0.12))

            try:
                detail_page.goto(url, wait_until="domcontentloaded", timeout=30000)

                try:
                    _wait_for_item_content(detail_page, timeout_ms=7000)
                except PlaywrightTimeoutError:
                    pass

                title = detail_page.title()
                title = _fast_clean_text(title) if title else None

                body_text = detail_page.inner_text("body") or ""
                body_text = _fast_clean_text(body_text)

                if _looks_like_generic_page(title, body_text):
                    debug["detail_fail"] += 1
                    continue

                desc = _extract_real_desc_from_body(body_text)
                price = _extract_price_from_page_text(body_text)

                modelo_desc, versao, memoria_interna, memoria_ram = _extract_specs_from_description(desc)
                modelo = modelo_desc if modelo_desc else _extract_model_from_title(title)

                collected.append(XianyuAd(
                    anuncio_id=_extract_id_from_url(url),
                    modelo=modelo,
                    versao=versao,
                    memoria_interna=memoria_interna,
                    memoria_ram=memoria_ram,
                    titulo=title,
                    preco=normalize_price(price),
                    descricao=desc,
                    vendedor=None,
                    origem_anuncio=origem,
                    url_anuncio=url,
                ))

                debug["detail_success"] += 1

            except Exception as e:
                print(f"Erro ao processar {url}: {e}")
                debug["detail_fail"] += 1
                continue

        detail_page.close()
        page.close()
        context.close()

    return collected, debug

def main():
    parser = argparse.ArgumentParser(description="Scraper do Xianyu (goofish.com) a partir do perfil do vendedor.")
    parser.add_argument("--profile-url", required=True)
    parser.add_argument("--limit", type=int, default=30)
    parser.add_argument("--headless", action="store_true")
    args = parser.parse_args()

    _ensure_dirs()

    ads, debug = scrape_vendor_profile(
        profile_url=args.profile_url,
        limit=args.limit,
        headless=args.headless,  # primeira vez: NÃO use --headless
    )

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = Path(f"data/raw/anuncios_xianyu_vendor_{ts}.jsonl")
    _save_jsonl([asdict(a) for a in ads], out_path)

    print("\n=== Xianyu Scraper (PERSISTENT SESSION) ===")
    print("Profile:", debug["profile_url"])
    print("Item URLs encontrados:", debug["found_item_urls"])
    print("Detalhes OK:", debug["detail_success"])
    print("Detalhes FAIL:", debug["detail_fail"])
    print("Arquivo gerado:", out_path.resolve())


if __name__ == "__main__":
    main()
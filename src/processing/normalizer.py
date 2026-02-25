import re
from typing import Optional, Dict, Any

RE_SPACES = re.compile(r"\s+")

# ---------- PREÇO ----------
RE_PRICE = re.compile(r"[¥￥]\s*([0-9]{1,6}(?:[.,][0-9]{1,2})?)")
RE_PRICE_FALLBACK = re.compile(r"\b([0-9]{2,6})\b")

# ---------- MODELO / SPECS ----------
RE_IPHONE_NUM = re.compile(r"(?:iphone|苹果)\s*([0-9]{2})", re.IGNORECASE)

RE_PROMAX = re.compile(r"(pro\s*max|promax|promax版|pm\b)", re.IGNORECASE)
RE_PRO = re.compile(r"\bpro\b|pro版|专业版", re.IGNORECASE)
RE_PLUS = re.compile(r"\bplus\b|plus版", re.IGNORECASE)
RE_MAX = re.compile(r"\bmax\b|max版", re.IGNORECASE)

RE_STORAGE_GB = re.compile(r"\b(128|256|512)\s*(?:g|gb)\b", re.IGNORECASE)
RE_STORAGE_TB = re.compile(r"\b(1)\s*(?:tb)\b", re.IGNORECASE)

# ---------- FLAGS (opcional) ----------
RE_BATTERY = re.compile(r"电池(?:效率)?\s*[:：]?\s*(\d{2,3})\s*%?")
RE_DUAL_SIM = re.compile(r"(双卡)")
RE_DISASSEMBLY = re.compile(r"(拆修|维修|更换)")
RE_SCREEN_ISSUE = re.compile(r"(漏液|烧屏|亮点|黑点|花屏)")

# ---------- LABELS ROBUSTOS ----------
# padrões que reconhecem labels com/sem espaços entre caracteres
LABEL_PATTERNS = {
    "modelo": r"(?:型\s*号|型号)",
    "storage": r"(?:存\s*储\s*容\s*量|存储容量)",
    "ram": r"(?:运\s*行\s*内\s*存|运行内存)",
    "version": r"(?:版\s*本|版本)",
    "brand": r"(?:品\s*牌|品牌)",
    "condition": r"(?:成\s*色|成色)",
}

ALL_LABELS_LOOKAHEAD = (
    rf"(?:{LABEL_PATTERNS['brand']}|{LABEL_PATTERNS['modelo']}|{LABEL_PATTERNS['storage']}|"
    rf"{LABEL_PATTERNS['ram']}|{LABEL_PATTERNS['version']}|{LABEL_PATTERNS['condition']})"
)

# remove qualquer resto de label colado no modelo
RE_MODEL_TRASH_TAIL = re.compile(rf"\s*{LABEL_PATTERNS['storage']}\s*[:：].*$", re.IGNORECASE)
RE_MODEL_TRASH_ANY = re.compile(rf"\s*{ALL_LABELS_LOOKAHEAD}\s*[:：].*$", re.IGNORECASE)


def _norm(s: Optional[str]) -> Optional[str]:
    if not s:
        return None
    return RE_SPACES.sub(" ", s).strip()


def normalize_price(price: Optional[str]) -> Optional[int]:
    if price is None:
        return None

    p = str(price).strip()

    m = RE_PRICE.search(p)
    if m:
        try:
            # se vier com , ou . em formatos estranhos
            return int(m.group(1).replace(",", "").replace(".", "").strip())
        except ValueError:
            pass

    m2 = RE_PRICE_FALLBACK.search(p)
    if m2:
        try:
            return int(m2.group(1))
        except ValueError:
            pass

    if p.isdigit():
        return int(p)

    return None


def _extract_field(text: str, label_key: str) -> Optional[str]:
    """
    Extrai com robustez:
      型 号 ： <valor>   (para quando o texto vem numa linha só)
    Para no próximo label conhecido, mesmo com espaços entre caracteres.
    """
    if not text:
        return None

    t = _norm(text) or ""
    label_pat = LABEL_PATTERNS[label_key]

    # captura até antes do próximo label conhecido + ":" ou fim do texto
    pattern = rf"{label_pat}\s*[:：]\s*(.*?)(?=\s*{ALL_LABELS_LOOKAHEAD}\s*[:：]|$)"
    m = re.search(pattern, t, flags=re.IGNORECASE)
    if not m:
        return None

    val = m.group(1).strip().replace("展开", "").strip()
    return val or None


def _normalize_version(text: str) -> Optional[str]:
    if not text:
        return None
    t = _norm(text) or ""

    if "海外无锁" in t or "无锁" in t or "美版" in t or "海外" in t:
        return "海外无锁"
    if "国行" in t or "大陆" in t:
        return "国行"
    if "港版" in t:
        return "港版"
    if "日版" in t:
        return "日版"

    return t


def _detect_variant(text: str) -> Optional[str]:
    if not text:
        return None
    t = text.lower()

    if RE_PROMAX.search(t):
        return "Pro Max"
    if RE_PRO.search(t):
        return "Pro"
    if RE_PLUS.search(t):
        return "Plus"
    if RE_MAX.search(t):
        return "Max"
    return None


def _normalize_storage(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None

    s = (_norm(raw) or "").upper().replace(" ", "")
    # normaliza 256G -> 256GB
    if re.fullmatch(r"(128|256|512)G", s):
        s = s.replace("G", "GB")

    if s in ("128GB", "256GB", "512GB", "1TB"):
        return s

    m_tb = RE_STORAGE_TB.search(s)
    if m_tb:
        return "1TB"
    m_gb = RE_STORAGE_GB.search(s)
    if m_gb:
        return f"{m_gb.group(1)}GB"

    return None


def normalize_model_fields(title: Optional[str], desc: Optional[str]) -> Dict[str, Any]:
    modelo = None
    versao = None
    memoria_interna = None
    memoria_ram = None

    # 1) tenta labels na descrição
    if desc:
        raw_model = _extract_field(desc, "modelo")
        raw_version = _extract_field(desc, "version")
        raw_storage = _extract_field(desc, "storage")
        raw_ram = _extract_field(desc, "ram")

        if raw_model:
            rm = raw_model.replace("Apple/苹果", "").strip()
            # ✅ remove qualquer label colado no final (bug que você viu)
            rm = RE_MODEL_TRASH_TAIL.sub("", rm).strip()
            rm = RE_MODEL_TRASH_ANY.sub("", rm).strip()
            modelo = _norm(rm)

        if raw_version:
            versao = _normalize_version(raw_version)

        if raw_storage:
            memoria_interna = _normalize_storage(raw_storage)

        if raw_ram:
            rr = _norm(raw_ram)
            if rr:
                memoria_ram = rr.upper().replace(" ", "")

    # 2) complemento por regex (título + descrição)
    src = " ".join([_norm(title) or "", _norm(desc) or ""]).strip()
    src_lower = src.lower()

    if not modelo:
        m_phone = RE_IPHONE_NUM.search(src)
        if m_phone:
            modelo = f"iPhone {m_phone.group(1)}"

    # variante (Pro/Max/Plus)
    if modelo:
        variant = _detect_variant(src_lower)
        if variant and variant.lower() not in modelo.lower():
            modelo = f"{modelo} {variant}"

    # memória interna por regex (se não veio por label)
    if not memoria_interna:
        m_tb = RE_STORAGE_TB.search(src)
        m_gb = RE_STORAGE_GB.search(src)
        if m_tb:
            memoria_interna = "1TB"
        elif m_gb:
            memoria_interna = f"{m_gb.group(1)}GB"

    # versão por sinais (se não veio por label)
    if not versao:
        versao = _normalize_version(src)

    # limpeza final
    modelo = _norm(modelo)
    if modelo:
        # remove qualquer memória se aparecer no modelo
        modelo = re.sub(r"\b(128GB|256GB|512GB|1TB)\b", "", modelo, flags=re.I).strip()
        # remove qualquer resto de label (garantia extra)
        modelo = RE_MODEL_TRASH_ANY.sub("", modelo).strip()
        modelo = _norm(modelo)

    return {
        "modelo": modelo,
        "versao": _norm(versao),
        "memoria_interna": _norm(memoria_interna),
        "memoria_ram": _norm(memoria_ram),
    }


def extract_commercial_flags(desc: Optional[str]) -> Dict[str, Any]:
    if not desc:
        return {}

    d = _norm(desc) or ""

    bateria = None
    m_bat = RE_BATTERY.search(d)
    if m_bat:
        try:
            bateria = int(m_bat.group(1))
        except ValueError:
            bateria = None

    return {
        "bateria_percentual": bateria,
        "dual_sim": bool(RE_DUAL_SIM.search(d)),
        "tem_desmontagem": bool(RE_DISASSEMBLY.search(d)),
        "tem_problema_tela": bool(RE_SCREEN_ISSUE.search(d)),
    }
"""OCR local (RapidOCR/ONNX) para páginas sem texto digital.

Devolve as caixas de texto com posição em pontos PDF, para o mesmo extrator por coordenadas.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import numpy as np

from .extratos import Pagina

DPI = 200
_engine = None


def _motor():
    global _engine
    if _engine is None:
        from rapidocr_onnxruntime import RapidOCR
        _engine = RapidOCR()
    return _engine


def _normaliza(t: str) -> str:
    """Corrige leituras de valores: '1.800.00' -> '1.800,00', '- 532,11' -> '-532,11'."""
    t = t.strip().replace(" ", "")
    m = re.match(r"^(-?)([\d.,]+)[.,](\d{2})(-?)$", t)
    if m and re.search(r"\d", m.group(2)):
        inteiro = int(re.sub(r"\D", "", m.group(2)))
        return f"{m.group(1)}{inteiro:,}".replace(",", ".") + f",{m.group(3)}{m.group(4)}"
    return t


CACHE = Path(__file__).resolve().parent.parent / "dados" / "cache_ocr"


def pagina_ocr(page, numero: int) -> Pagina:
    """OCR com cache em disco: cada página é lida uma vez só."""
    chave = hashlib.sha1(page.parent.name.encode() + str(numero).encode() + page.get_contents_hash()).hexdigest()         if hasattr(page, "get_contents_hash") else hashlib.sha1(f"{page.parent.name}|{numero}".encode()).hexdigest()
    arq = CACHE / f"{chave}.json"
    if arq.exists():
        d = json.loads(arq.read_text(encoding="utf-8"))
        return Pagina(numero, [tuple(p) for p in d["palavras"]], d["texto"], ocr=True)
    pg = _ler(page, numero)
    CACHE.mkdir(parents=True, exist_ok=True)
    arq.write_text(json.dumps({"palavras": pg.palavras, "texto": pg.texto}, ensure_ascii=False), encoding="utf-8")
    return pg


def _ler(page, numero: int) -> Pagina:
    pix = page.get_pixmap(dpi=DPI)
    img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)[:, :, :3]
    res, _ = _motor()(img)
    k = 72 / DPI
    palavras, linhas = [], []
    for caixa, texto, conf in res or []:
        xs = [p[0] for p in caixa]
        ys = [p[1] for p in caixa]
        x0, y0, x1, y1 = min(xs) * k, min(ys) * k, max(xs) * k, max(ys) * k
        texto = _normaliza(texto)
        palavras.append((x0, y0, x1, y1, texto))
        linhas.append(texto)
    return Pagina(numero, palavras, "\n".join(linhas), ocr=True)

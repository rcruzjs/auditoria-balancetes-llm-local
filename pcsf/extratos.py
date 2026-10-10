"""Extração dos extratos bancários (Santander) embutidos nos balancetes do PCSF.

Dois layouts aparecem nos PDFs:
  A) "Internet Banking Empresarial" (jan–set/2025): uma linha por lançamento, data em toda linha,
     valor com sinal e saldo ao fim do dia.
  B) "Extrato Consolidado Inteligente" (out/2025 em diante): data só no primeiro lançamento do dia,
     créditos e débitos em colunas separadas, e um resumo por conta com os totais do mês.

A extração usa a posição das palavras na página (texto digital), sem OCR e sem LLM.
Páginas escaneadas são apenas sinalizadas aqui; o OCR fica em outro módulo.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

import pymupdf

VALOR = re.compile(r"^-?\d{1,3}(\.\d{3})*,\d{2}-?$")
DATA_LONGA = re.compile(r"^\d{2}/\d{2}/\d{4}$")
DATA_CURTA = re.compile(r"^\d{2}/\d{2}$")
MESES = {"janeiro": 1, "fevereiro": 2, "março": 3, "marco": 3, "abril": 4, "maio": 5, "junho": 6,
         "julho": 7, "agosto": 8, "setembro": 9, "outubro": 10, "novembro": 11, "dezembro": 12}


def valor(t: str) -> Decimal:
    neg = t.startswith("-") or t.endswith("-")
    v = Decimal(t.strip("-").replace(".", "").replace(",", "."))
    return -v if neg else v


def so_digitos(s: str) -> str:
    return re.sub(r"\D", "", s)


@dataclass
class Lancamento:
    pagina: int
    conta: str | None
    data: date | None
    descricao: str
    documento: str | None
    valor: Decimal | None          # None = linha só de saldo (ex.: SALDO ANTERIOR)
    saldo: Decimal | None = None   # saldo impresso pelo banco após o lançamento
    formato: str = ""
    linha_y: float = 0.0           # posição vertical na página (para destacar no PDF)
    bloco: int = 0                 # impressão/seção do extrato de onde veio (para deduplicar)


@dataclass
class ResumoConta:
    conta: str
    saldo_inicial: Decimal | None = None
    total_creditos: Decimal | None = None
    total_debitos: Decimal | None = None
    saldo_final: Decimal | None = None
    pagina: int = 0


@dataclass
class Extracao:
    lancamentos: list[Lancamento] = field(default_factory=list)
    resumos: list[ResumoConta] = field(default_factory=list)
    paginas_escaneadas: list[int] = field(default_factory=list)
    paginas_extrato: list[int] = field(default_factory=list)


@dataclass
class Pagina:
    """Palavras de uma página com posição em pontos PDF, vindas do texto digital ou do OCR."""
    numero: int
    palavras: list[tuple[float, float, float, float, str]]
    texto: str
    ocr: bool = False


def _pagina_texto(page, numero: int) -> Pagina:
    return Pagina(numero, [tuple(w[:5]) for w in page.get_text("words")], page.get_text())


def _linhas(pg: Pagina, tol=1.6):
    """Agrupa as palavras em linhas visuais: [(y, [(x0, x1, texto), ...]), ...]."""
    ws = sorted((round(w[1], 1), w[0], w[2], w[4]) for w in pg.palavras)
    tol = 4.0 if pg.ocr else tol
    out: list[list] = []
    for y, x0, x1, t in ws:
        if out and y - out[-1][0] <= tol:
            out[-1][1].append((x0, x1, t))
        else:
            out.append([y, [(x0, x1, t)]])
    for linha in out:
        linha[1].sort()
    return out


def _texto(ws, x_min, x_max):
    return " ".join(t for x0, x1, t in ws if x_min <= x0 < x_max).strip()


# ----------------------------------------------------------------------------- formato A
def _pagina_a(pg: Pagina, estado, ex: Extracao):
    txt, pno = pg.texto, pg.numero
    if "InternetBankingEmpresarial" in txt.replace(" ", ""):
        estado["bloco"] = estado.get("bloco", 0) + 1
        m = re.search(r"Conta:\s*(\d{6,})", txt) or re.search(r"(\d{9})", txt)
        if m:
            estado["conta"] = m.group(1)
        estado["em_mov"] = False
    for y, ws in _linhas(pg):
        tokens = [t for _, _, t in ws]
        # cabeçalho define as colunas (a impressão de julho/2025 tem outra escala)
        hdr = {t.rstrip(":").lower()[:5]: (x0, x1) for x0, x1, t in ws}
        if "docum" in hdr and ("histó" in hdr or "histo" in hdr):
            estado["em_mov"] = True
            estado["col_data"] = hdr.get("data", (30, 0))[0]
            estado["col_doc"] = hdr["docum"][0]
            estado["col_saldo"] = next((x0 for x0, x1, t in ws if t.lower().startswith("sald")), 530)
            continue
        if not estado.get("em_mov"):
            continue
        cd, cdoc, csal = estado.get("col_data", 40), estado.get("col_doc", 412), estado.get("col_saldo", 537)
        d = [t for x0, x1, t in ws if cd - 12 <= x0 <= cd + 12 and DATA_LONGA.match(t)]
        if not d:
            continue
        dia, mes, ano = map(int, d[0].split("/"))
        x_desc = next(x1 for x0, x1, t in ws if t == d[0]) + 5
        desc = _texto(ws, x_desc, cdoc - 8)
        doc = _texto(ws, cdoc - 8, cdoc + 40) or None
        val = [t for x0, x1, t in ws if cdoc + 40 <= x0 < csal - 15 and VALOR.match(t)]
        sal = [t for x0, x1, t in ws if x0 >= csal - 15 and VALOR.match(t)]
        ex.lancamentos.append(Lancamento(
            pagina=pno, conta=estado.get("conta"), data=date(ano, mes, dia), descricao=desc, documento=doc,
            valor=valor(val[0]) if val else None, saldo=valor(sal[0]) if sal else None,
            formato="A-ocr" if pg.ocr else "A", linha_y=y, bloco=estado.get("bloco", 0),
        ))
        if pno not in ex.paginas_extrato:
            ex.paginas_extrato.append(pno)


# ----------------------------------------------------------------------------- formato B
def _pagina_b(pg: Pagina, estado, ex: Extracao):
    txt, pno = pg.texto, pg.numero
    m = re.search(r"\b(" + "|".join(MESES) + r")\s*/\s*(\d{4})", txt, re.IGNORECASE)
    if m:
        estado["ano"] = int(m.group(2))
        estado["mes"] = MESES.get(m.group(1).lower(), estado.get("mes"))

    if "Resumo - " in txt:
        mc = re.search(r"Conta Corrente\s*\n\s*([\d.\-]+)", txt)
        if mc:
            estado["conta"] = so_digitos(mc.group(1))
            estado["bloco"] = estado.get("bloco", 0) + 1
            r = ResumoConta(conta=estado["conta"], pagina=pno)

            def campo(rotulo):
                mm = re.search(rotulo + r"[^\n]*\n\s*(-?[\d.]+,\d{2}-?)", txt)
                return valor(mm.group(1).strip()) if mm else None

            r.saldo_inicial = campo(r"Saldo de Conta Corrente em \d{2}/\d{2}")
            r.total_creditos = campo(r"Total de Cr[ée]ditos")
            r.total_debitos = campo(r"Total de D[ée]bitos")
            finais = re.findall(r"Saldo de Conta Corrente em \d{2}/\d{2}[^\n]*\n\s*(-?[\d.]+,\d{2}-?)", txt)
            r.saldo_final = valor(finais[-1].strip()) if len(finais) > 1 else None
            ex.resumos.append(r)
        estado["em_mov"] = False

    for y, ws in _linhas(pg):
        tokens = [t for _, _, t in ws]
        linha = " ".join(tokens)
        # títulos de seção: só a movimentação da conta corrente interessa
        if linha in ("Conta Corrente", "Movimentação") or linha.startswith("Conta Corrente Movimenta"):
            estado["secao"] = "cc"
            continue
        if linha.startswith(("Investimentos", "ContaMax", "Produtos e Serviços", "Você e Seu Dinheiro",
                             "Pacote de Serviços", "Comprovante", "Fale Conosco", "Resumo - ")):
            estado["secao"] = "outra"
            estado["em_mov"] = False
            continue
        if "Data" in tokens and "Documento" in tokens:
            estado["em_mov"] = estado.get("secao") == "cc"
            continue
        if any(t.endswith("ditos") or t.endswith("bitos") for t in tokens) and len(tokens) <= 3:
            continue
        if not estado.get("em_mov") or y > 798 or y < 40:
            continue

        d = [t for x0, x1, t in ws if x1 < 55 and DATA_CURTA.match(t)]
        if d:
            dia, mes = map(int, d[0].split("/"))
            ano = estado.get("ano")
            if estado.get("mes") == 1 and mes == 12:   # saldo de 31/12 no extrato de janeiro
                ano -= 1
            estado["data"] = date(ano, mes, dia)
        desc = _texto(ws, 62, 295)   # x≈57: marca "A" (agendado) do banco, fora do histórico
        doc = _texto(ws, 295, 345) or None
        cred = [t for x0, x1, t in ws if 370 <= x1 <= 415 and VALOR.match(t)]
        deb = [t for x0, x1, t in ws if 415 < x1 <= 470 and VALOR.match(t)]
        sal = [t for x0, x1, t in ws if x0 > 480 and VALOR.match(t)]
        if (cred or deb) and re.search(r"[A-Za-z]", desc):
            v = valor(cred[0]) if cred else -abs(valor(deb[0]))
            ex.lancamentos.append(Lancamento(
                pagina=pno, conta=estado.get("conta"), data=estado.get("data"), descricao=desc, documento=doc,
                valor=v, saldo=valor(sal[0]) if sal else None, formato="B", linha_y=y, bloco=estado.get("bloco", 0),
            ))
            estado["ultimo"] = ex.lancamentos[-1]
            if pno not in ex.paginas_extrato:
                ex.paginas_extrato.append(pno)
        elif sal and "SALDO ANTERIOR" in desc.upper():
            ex.lancamentos.append(Lancamento(
                pagina=pno, conta=estado.get("conta"), data=estado.get("data"), descricao="SALDO ANTERIOR",
                documento=None, valor=None, saldo=valor(sal[0]), formato="B", linha_y=y,
            ))
            estado["ultimo"] = None
        elif desc and estado.get("ultimo") is not None and not d:
            # continuação da descrição (nome do recebedor, conta de destino...)
            estado["ultimo"].descricao += " | " + desc
            if doc and not estado["ultimo"].documento:
                estado["ultimo"].documento = doc


# ----------------------------------------------------------------------------- entrada
def extrair(caminho: str, ocr=None) -> Extracao:
    """ocr: função (page) -> Pagina para páginas sem texto digital; sem ela, só são sinalizadas."""
    ex = Extracao()
    estado: dict = {}
    with pymupdf.open(caminho) as pdf:
        for pno, page in enumerate(pdf, 1):
            pg = _pagina_texto(page, pno)
            if len(pg.texto.strip()) < 80 and (page.get_images() or len(page.get_drawings()) > 200):
                ex.paginas_escaneadas.append(pno)
                if ocr is None:
                    continue
                pg = ocr(page, pno)
            txt = pg.texto
            if "InternetBankingEmpresarial" in txt.replace(" ", ""):
                estado["fmt"] = "A"
                _pagina_a(pg, estado, ex)
            elif "Extrato_PJ_A4_Inteligente" in txt:
                estado["fmt"] = "B"
                _pagina_b(pg, estado, ex)
            elif estado.get("fmt") == "A" and re.search(r"\d{2}/\d{2}/\d{4}", txt[:200]):
                _pagina_a(pg, estado, ex)
            else:
                estado["em_mov"] = False
    return ex

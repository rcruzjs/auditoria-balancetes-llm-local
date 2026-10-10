"""Extração do Balancete Analítico (contabilidade) dos PDFs do PCSF.

Cada página tem as colunas: Descrição | Saldo Anterior | Débito | Crédito | Saldo Atual.
As contas aparecem como "[código]Descrição", indentadas por nível. Grupos têm uma linha de abertura
sem valores ("[31010]Diretoria Social e Cultural") e uma linha de total ("=Diretoria Social e Cultural")
com os valores do grupo. Os saldos trazem a natureza no fim (C = credor, D = devedor).

Isto é separado dos movimentos bancários: vai para a tabela `balancete`.
"""
from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from decimal import Decimal

import pymupdf

VAL = re.compile(r"^-?\d{1,3}(\.\d{3})*,\d{2}[CD]?$")
COD = re.compile(r"^\[(\d+)\](.*)$")
# colunas pela borda direita do número (pontos PDF)
COLUNAS = {"saldo_anterior": (335, 365), "debito": (400, 432), "credito": (468, 502), "saldo_atual": (540, 575)}


def _num(t: str) -> tuple[Decimal, str | None]:
    nat = t[-1] if t[-1] in "CD" else None
    return Decimal(t.rstrip("CD").replace(".", "").replace(",", ".")), nat


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().upper()
    return re.sub(r"[^A-Z0-9]", "", s)


@dataclass
class Linha:
    pagina: int
    codigo: str | None
    descricao: str
    tipo: str                       # 'conta' (folha), 'grupo' (total de grupo), 'total' (total sem código)
    nivel: int
    grupo_codigo: str | None = None  # grupo imediatamente acima
    grupo_descricao: str | None = None
    saldo_anterior: Decimal | None = None
    saldo_anterior_nat: str | None = None
    debito: Decimal | None = None
    credito: Decimal | None = None
    saldo_atual: Decimal | None = None
    saldo_atual_nat: str | None = None
    filhos: list = field(default_factory=list, repr=False)

    def saldo_assinado(self, atual=True) -> Decimal:
        """Devedor positivo, credor negativo."""
        v, n = (self.saldo_atual, self.saldo_atual_nat) if atual else (self.saldo_anterior, self.saldo_anterior_nat)
        v = v or Decimal(0)
        return -v if n == "C" else v


def _linhas_pagina(page):
    ws = sorted((round(w[1], 1), w[0], w[2], w[4]) for w in page.get_text("words") if w[1] > 72)
    out = []
    for y, x0, x1, t in ws:
        if out and y - out[-1][0] <= 1.6:
            out[-1][1].append((x0, x1, t))
        else:
            out.append([y, [(x0, x1, t)]])
    for l in out:
        l[1].sort()
    return out


def extrair(caminho: str) -> list[Linha]:
    linhas: list[Linha] = []
    pilha: list[tuple[float, Linha]] = []   # grupos abertos: (x0, linha de abertura)
    with pymupdf.open(caminho) as pdf:
        for pno, page in enumerate(pdf, 1):
            txt = page.get_text()
            if "Balancete Anal" not in txt or "Saldo Anterior" not in txt:
                continue
            for y, ws in _linhas_pagina(page):
                if ws[0][2].startswith("Declaro"):
                    break
                rot = [(x0, t) for x0, x1, t in ws if x0 < 300]
                vals = {}
                for x0, x1, t in ws:
                    if x0 >= 300 and VAL.match(t):
                        for col, (a, b) in COLUNAS.items():
                            if a <= x1 <= b:
                                vals[col] = _num(t)
                if not rot:
                    continue
                x_rot = rot[0][0]
                texto = " ".join(t for _, t in rot).strip()
                m = COD.match(texto)
                if m:
                    codigo, desc = m.group(1), m.group(2).strip()
                    while pilha and pilha[-1][0] >= x_rot:
                        pilha.pop()
                    pai = pilha[-1][1] if pilha else None
                    l = Linha(pno, codigo, desc, "conta", len(pilha) + 1,
                              pai.codigo if pai else None, pai.descricao if pai else None)
                    if vals:
                        _valores(l, vals)
                        linhas.append(l)
                        if pai:
                            pai.filhos.append(l)
                    else:
                        l.tipo = "grupo"          # abertura de grupo; valores chegam na linha "=..."
                        pilha.append((x_rot, l))
                elif texto.startswith("=") and vals:
                    desc = re.sub(r"(?<=\b\w) (?=\w\b)", "", texto[1:]).strip()   # "T o t a l" -> "Total"
                    alvo = next((i for i in range(len(pilha) - 1, -1, -1)
                                 if _norm(pilha[i][1].descricao) == _norm(desc)), None)
                    if alvo is not None:
                        g = pilha[alvo][1]
                        _valores(g, vals)
                        del pilha[alvo:]
                        linhas.append(g)
                        if pilha:
                            pilha[-1][1].filhos.append(g)
                    else:
                        t = Linha(pno, None, desc, "total", 0)
                        _valores(t, vals)
                        linhas.append(t)
    return linhas


def _valores(l: Linha, vals: dict) -> None:
    if "saldo_anterior" in vals:
        l.saldo_anterior, l.saldo_anterior_nat = vals["saldo_anterior"]
    if "debito" in vals:
        l.debito = vals["debito"][0]
    if "credito" in vals:
        l.credito = vals["credito"][0]
    if "saldo_atual" in vals:
        l.saldo_atual, l.saldo_atual_nat = vals["saldo_atual"]


def conferir(linhas: list[Linha]) -> dict:
    """Conferências contábeis da extração:
    - grupos: débito e crédito do total = soma dos filhos diretos;
    - saldo: saldo anterior + débito - crédito = saldo atual (devedor positivo);
    - partidas dobradas: soma dos débitos das contas = soma dos créditos."""
    falhas = []
    for l in linhas:
        if l.tipo == "grupo" and l.filhos:
            for col in ("debito", "credito"):
                soma = sum((getattr(f, col) or Decimal(0)) for f in l.filhos)
                if soma != (getattr(l, col) or Decimal(0)):
                    falhas.append(f"grupo [{l.codigo}] {l.descricao}: {col} {getattr(l, col)} ≠ soma dos filhos {soma}")
        if l.tipo in ("conta", "grupo") and l.saldo_atual is not None:
            esperado = l.saldo_assinado(False) + (l.debito or 0) - (l.credito or 0)
            if esperado != l.saldo_assinado(True):
                falhas.append(f"saldo [{l.codigo}] {l.descricao}: esperado {esperado}, impresso {l.saldo_assinado(True)}")
    contas = [l for l in linhas if l.tipo == "conta"]
    deb = sum((l.debito or Decimal(0)) for l in contas)
    cred = sum((l.credito or Decimal(0)) for l in contas)
    return {"linhas": len(linhas), "contas": len(contas), "grupos": sum(l.tipo == "grupo" for l in linhas),
            "debitos": deb, "creditos": cred, "partidas_dobradas": deb == cred, "falhas": falhas}


def gravar(con, documento_id: int, competencia, caminho: str) -> dict:
    """Extrai, confere e grava o balancete de um arquivo (substitui o que houver desse documento)."""
    linhas = extrair(caminho)
    c = conferir(linhas)
    con.execute("DELETE FROM balancete WHERE documento_id = %s", (documento_id,))
    with con.cursor() as cur:
        cur.executemany(
            """INSERT INTO balancete (documento_id, competencia, pagina, codigo, descricao, tipo, nivel,
                                      grupo_codigo, grupo_descricao, saldo_anterior, saldo_anterior_nat,
                                      debito, credito, saldo_atual, saldo_atual_nat)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            [(documento_id, competencia, l.pagina, l.codigo, l.descricao, l.tipo, l.nivel, l.grupo_codigo,
              l.grupo_descricao, l.saldo_anterior, l.saldo_anterior_nat, l.debito, l.credito, l.saldo_atual,
              l.saldo_atual_nat) for l in linhas])
    ok = c["partidas_dobradas"] and not c["falhas"]
    con.execute(
        """INSERT INTO conciliacoes (documento_id, conta, tipo, creditos_extraidos, debitos_extraidos, ok, detalhe)
           VALUES (%s, 'contabil', 'balancete', %s, %s, %s, %s)""",
        (documento_id, c["creditos"], c["debitos"], ok, json.dumps(c["falhas"][:50]) if c["falhas"] else None))
    return c


def main():
    """Carrega o balancete de todos os documentos já cadastrados."""
    from pathlib import Path
    from .db import conectar
    pasta = Path(__file__).resolve().parent.parent / "balancetes pcsf"
    with conectar() as con:
        con.execute("DELETE FROM conciliacoes WHERE tipo = 'balancete'")
        for doc_id, arquivo, comp in con.execute("SELECT id, arquivo, competencia FROM documentos ORDER BY competencia").fetchall():
            c = gravar(con, doc_id, comp, str(pasta / arquivo))
            print(f"  {arquivo}: {c['linhas']} linhas, partidas dobradas {'OK' if c['partidas_dobradas'] else 'NÃO'}, "
                  f"{len(c['falhas'])} falhas", flush=True)
        con.commit()


if __name__ == "__main__":
    main()

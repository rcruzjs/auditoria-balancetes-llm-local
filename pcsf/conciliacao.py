"""Conferência da extração contra os números do próprio banco.

1. Saldo corrido: entre dois saldos impressos, saldo anterior + soma dos lançamentos = saldo impresso.
2. Resumo mensal (formato B): soma dos créditos e dos débitos de cada conta = totais do resumo.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal

from .extratos import Extracao


@dataclass
class Trecho:
    conta: str | None
    pagina: int
    data: object
    esperado: Decimal
    impresso: Decimal

    @property
    def ok(self) -> bool:
        return self.esperado == self.impresso


def saldo_corrido(ex: Extracao) -> list[Trecho]:
    trechos: list[Trecho] = []
    saldo: dict = {}
    soma: dict = defaultdict(Decimal)
    for l in ex.lancamentos:
        c = l.conta
        if l.valor is not None:
            soma[c] += l.valor
        if l.saldo is not None:
            if c in saldo:
                trechos.append(Trecho(c, l.pagina, l.data, saldo[c] + soma[c], l.saldo))
            saldo[c], soma[c] = l.saldo, Decimal(0)
    return trechos


def resumo_mensal(ex: Extracao) -> list[dict]:
    out = []
    for r in ex.resumos:
        ls = [l for l in ex.lancamentos if l.conta == r.conta and l.valor is not None and l.formato == "B"]
        cred = sum((l.valor for l in ls if l.valor > 0), Decimal(0))
        deb = -sum((l.valor for l in ls if l.valor < 0), Decimal(0))
        out.append({
            "conta": r.conta, "lancamentos": len(ls),
            "creditos_extraidos": cred, "creditos_banco": r.total_creditos,
            "debitos_extraidos": deb, "debitos_banco": r.total_debitos,
            # conta sem movimento: o banco não imprime totais
            "ok": (r.total_creditos or 0) == cred and (r.total_debitos or 0) == deb,
        })
    return out

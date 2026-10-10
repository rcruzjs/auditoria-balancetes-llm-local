"""Dados que identificam o clube auditado (nome, CNPJ, contas bancárias).

Ficam no .env, fora do Git; veja os exemplos em .env.example. Sem eles o sistema funciona, mas não reconhece
as transferências entre contas do próprio clube como movimentos internos.
"""
from __future__ import annotations

import os

from . import db  # noqa: F401  (carrega o .env)


def _lista(nome: str) -> tuple[str, ...]:
    return tuple(x.strip() for x in os.environ.get(nome, "").split(",") if x.strip())


NOME = os.environ.get("CLUBE_NOME", "Clube")
CNPJ = os.environ.get("CLUBE_CNPJ", "")
NOME_EXTRATO = os.environ.get("CLUBE_NOME_EXTRATO", "")        # nome como aparece no extrato, sem espaços
CONTAS = _lista("CLUBE_CONTAS")                                 # contas Santander, só dígitos
CONTAS_SICREDI = _lista("CLUBE_CONTAS_SICREDI")                 # banco + agência + conta, só dígitos
SICREDI_PADRAO = os.environ.get("CLUBE_SICREDI_PADRAO", "")     # trecho do histórico das TEDs para o Sicredi
# código da conta no balancete contábil -> conta bancária ("201:130000000,202:...")
CONTAS_BALANCETE = dict(par.split(":", 1) for par in _lista("CLUBE_CONTAS_BALANCETE"))

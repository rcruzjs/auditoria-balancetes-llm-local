"""Competência (mês/ano) lida do nome do arquivo do balancete."""
from datetime import date

import pytest

from pcsf.carga import competencia


def test_competencia_padrao_do_projeto():
    assert competencia("Balancete 2025-07-JUL.pdf") == date(2025, 7, 1)


def test_competencia_pelo_nome_do_mes():
    assert competencia("Balancete JUL 2025.pdf") == date(2025, 7, 1)


def test_competencia_invalida():
    with pytest.raises(ValueError):
        competencia("extrato.pdf")

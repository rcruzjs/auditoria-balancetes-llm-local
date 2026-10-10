"""Conversão dos valores impressos no extrato (formato brasileiro, sinal antes ou depois)."""
from decimal import Decimal

from pcsf.extratos import so_digitos, valor


def test_valor_positivo():
    assert valor("1.234,56") == Decimal("1234.56")


def test_valor_negativo_com_sinal_antes_ou_depois():
    assert valor("-1.234,56") == Decimal("-1234.56")
    assert valor("1.234,56-") == Decimal("-1234.56")


def test_valor_sem_milhar():
    assert valor("0,99") == Decimal("0.99")


def test_so_digitos():
    assert so_digitos("12.345.678/0001-99") == "12345678000199"

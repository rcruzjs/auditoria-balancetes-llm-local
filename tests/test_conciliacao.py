"""Conferência da extração contra os saldos e resumos impressos pelo banco."""
from decimal import Decimal as D

from pcsf.conciliacao import resumo_mensal, saldo_corrido
from pcsf.extratos import Extracao, Lancamento, ResumoConta


def lanc(valor, saldo=None, formato="B"):
    return Lancamento(pagina=1, conta="123", data=None, descricao="X", documento=None,
                      valor=None if valor is None else D(valor), saldo=None if saldo is None else D(saldo),
                      formato=formato)


def test_saldo_corrido_confere():
    ex = Extracao(lancamentos=[lanc(None, "100.00"), lanc("50.00"), lanc("-20.00", "130.00")])
    (trecho,) = saldo_corrido(ex)
    assert trecho.ok and trecho.esperado == D("130.00")


def test_saldo_corrido_detecta_divergencia():
    ex = Extracao(lancamentos=[lanc(None, "100.00"), lanc("50.00", "151.00")])
    (trecho,) = saldo_corrido(ex)
    assert not trecho.ok


def test_resumo_mensal():
    ex = Extracao(lancamentos=[lanc("50.00"), lanc("-20.00"), lanc("-5.00")],
                  resumos=[ResumoConta("123", total_creditos=D("50.00"), total_debitos=D("25.00"))])
    (r,) = resumo_mensal(ex)
    assert r["ok"] and r["debitos_extraidos"] == D("25.00")


def test_resumo_mensal_ignora_formato_a():
    ex = Extracao(lancamentos=[lanc("50.00", formato="A")],
                  resumos=[ResumoConta("123", total_creditos=D("50.00"), total_debitos=D("0"))])
    assert not resumo_mensal(ex)[0]["ok"]

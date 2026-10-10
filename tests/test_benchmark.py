"""Comparador do benchmark: decide se o resultado do modelo bate com o da referência."""
from datetime import date
from decimal import Decimal as D

from avaliacao.benchmark import com_apelidos, confere

REF = [("2025-01", D("100.00")), ("2025-02", D("250.50"))]


def test_mesmo_resultado():
    assert confere(REF, [("2025-01", D("100.00")), ("2025-02", D("250.50"))])


def test_tolera_sinal_ordem_colunas_extras_e_formato_do_mes():
    assert confere(REF, [(D("-250.5"), "02/2025", 3), (D("-100"), "01/2025", 1)])


def test_valor_diferente_esta_errado():
    assert not confere(REF, [("2025-01", D("100.00")), ("2025-02", D("999.00"))])


def test_faltando_linha_esta_errado():
    assert not confere(REF, [("2025-01", D("100.00"))])


def test_linhas_demais_esta_errado():
    despejo = [("x", D("100.00")), ("y", D("250.50"))] + [("z", D(i)) for i in range(20)]
    assert not confere(REF, despejo)


def test_nome_da_referencia_precisa_aparecer():
    ref = [("Natação", D("10.00"))]
    assert confere(ref, [("NATAÇÃO", D("10"))])
    assert not confere(ref, [("Tênis", D("10"))])


def test_datas_e_nulos_nao_atrapalham():
    assert confere([(date(2025, 4, 30), None, D("5.00"))], [("30/04/2025", "PAGFOR", D("-5"))])


def test_apelidos_trocam_pergunta_e_sql():
    p = {"id": "x", "pergunta": "Gasto com o Bar Fictício?", "sql": "WHERE string = 'Bar Fictício'"}
    r = com_apelidos(p, {"Bar Fictício": "Bar Real"})
    assert r["pergunta"] == "Gasto com o Bar Real?" and r["sql"] == "WHERE string = 'Bar Real'"
    assert p["pergunta"] == "Gasto com o Bar Fictício?"  # não altera o original

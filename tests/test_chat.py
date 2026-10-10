"""Travas de segurança do chat NL→SQL e mascaramento de CPF (LGPD). Não acessam o banco nem o LLM."""
import pytest
from fastapi import HTTPException

from web.app import _sql_seguro, mascara, numeros_conferem


def test_sql_seguro_acrescenta_limit():
    assert _sql_seguro("SELECT * FROM v_movimentos;") == "SELECT * FROM v_movimentos LIMIT 500"


def test_sql_seguro_mantem_limit_existente():
    assert _sql_seguro("with x as (select 1) select * from x limit 10").endswith("limit 10")


@pytest.mark.parametrize("sql", [
    "DROP TABLE transacoes",
    "SELECT 1; DELETE FROM transacoes",
    "UPDATE transacoes SET valor = 0",
    "SELECT pg_sleep(60)",
    "EXPLAIN SELECT 1",
])
def test_sql_seguro_bloqueia(sql):
    with pytest.raises(HTTPException):
        _sql_seguro(sql)


def test_numeros_conferem_aceita_valor_do_resultado():
    assert numeros_conferem("O total foi R$ 1.234,56.", [[1234.56]])


def test_numeros_conferem_rejeita_valor_inventado():
    assert not numeros_conferem("O total foi R$ 9.999,00.", [[1234.56]])


def test_numeros_conferem_ignora_anos_e_numeros_pequenos():
    assert numeros_conferem("Em 2025 houve 12 eventos.", [[1.0]])


def test_mascara_cpf_mas_nao_cnpj():
    assert mascara("PIX RECEBIDO 12345678901") == "PIX RECEBIDO ***.456.789-**"
    assert mascara("12345678000199") == "12345678000199"

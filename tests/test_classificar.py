"""Regras determinísticas de tipo, movimento interno, contraparte e restauração de OCR.
Os nomes e documentos usados aqui são fictícios."""
import pytest

from pcsf import classificar
from pcsf.classificar import Vocabulario, contraparte, interna, tipo_de

CNPJ_FICTICIO = "11222333000181"


@pytest.fixture(autouse=True)
def clube_ficticio(monkeypatch):
    """Os dados reais do clube vêm do .env; nos testes usamos valores fictícios."""
    monkeypatch.setattr(classificar, "CNPJ_CLUBE", CNPJ_FICTICIO)
    monkeypatch.setattr(classificar, "NOME_CLUBE_EXTRATO", "CLUBEEXEMPLO")
    monkeypatch.setattr(classificar, "CONTAS_CLUBE", ("130000001",))
    monkeypatch.setattr(classificar, "CONTAS_CLUBE_SICREDI", ("7480000000000000001",))


@pytest.mark.parametrize("descricao, tipo", [
    ("PIX RECEBIDO FULANO DE TAL", "PIX_RECEBIDO"),
    ("PIXRECEBID0 FULANO", "PIX_RECEBIDO"),               # OCR troca O por 0
    ("PIX ENVIADO BELTRANO", "PIX_ENVIADO"),
    ("TED PGTO FORNECEDORES CIP", "PAGFOR_LOTE"),          # tem de vir antes de TED_ENVIADA
    ("TED ENVIADA 0001.1234567890 CICLANO", "TED_ENVIADA"),
    ("TARIFA MENSALIDADE PACOTE", "TARIFA"),
    ("APLICACAO CONTAMAX", "APLICACAO_RESGATE"),
    ("PAGAMENTO DE BOLETO OUTROS BANCOS EMPRESA X", "BOLETO"),
    ("HISTORICO DESCONHECIDO", "OUTROS"),
])
def test_tipo_de(descricao, tipo):
    assert tipo_de(descricao) == tipo


def test_interna_aplicacao_e_cnpj_do_clube():
    assert interna("APLICACAO CONTAMAX", "APLICACAO_RESGATE")
    assert interna(f"TED ENVIADA {CNPJ_FICTICIO}", "TED_ENVIADA")
    assert interna("PIX ENVIADO CLUBE EXEMPLO", "PIX_ENVIADO")


def test_interna_contas_do_clube():
    assert interna("TRANSF VALORES PARA: 13.000000-1", "TRANSFERENCIA")
    assert interna("TED ENVIADA 748 0000 000000000001", "TED_ENVIADA")


def test_sem_dados_do_clube_nada_vira_interno_por_engano(monkeypatch):
    monkeypatch.setattr(classificar, "CNPJ_CLUBE", "")
    monkeypatch.setattr(classificar, "NOME_CLUBE_EXTRATO", "")
    assert not interna("PIX ENVIADO FULANO DE TAL", "PIX_ENVIADO")


def test_interna_transferencia_mesmo_titular():
    assert interna("TRANSF VALORES MESMO TITULAR", "TRANSFERENCIA")


def test_pagamento_a_terceiro_nao_e_interno():
    assert not interna("PIX ENVIADO FULANO DE TAL", "PIX_ENVIADO")


def test_contraparte_pix_recebido_cpf_e_cnpj():
    cp = contraparte("PIX RECEBIDO 123 456 789 01", "PIX_RECEBIDO")
    assert (cp.doc, cp.tipo_doc) == ("12345678901", "CPF")
    cp = contraparte("PIX RECEBIDO 12345678000199", "PIX_RECEBIDO")
    assert (cp.doc, cp.tipo_doc) == ("12345678000199", "CNPJ")


def test_contraparte_pix_enviado_nome():
    cp = contraparte("PIX ENVIADO FULANO DE TAL", "PIX_ENVIADO")
    assert cp.nome == "FULANO DE TAL" and cp.doc is None


def test_contraparte_mei_raiz_do_cnpj():
    cp = contraparte("PIX ENVIADO 12 345 678 FULANO DE TAL", "PIX_ENVIADO")
    assert (cp.doc, cp.tipo_doc, cp.nome) == ("12345678", "CNPJ_RAIZ", "FULANO DE TAL")


def test_contraparte_transferencia_conta():
    cp = contraparte("TRANSF VALORES PARA: 13.000282-3", "TRANSFERENCIA")
    assert cp.nome == "CONTA 13.000282-3"


def test_vocabulario_restaura_espacos_do_ocr():
    vocab = Vocabulario(["PIX ENVIADO FULANO DE TAL"] * 15)
    assert vocab.restaurar("PIXENVIADOFulanodeTal") == "PIX ENVIADO FULANO DE TAL"
    # nome desconhecido: corta o prefixo do banco (tolerando O/0) e separa o CamelCase
    assert vocab.restaurar("PIXENVIAD0BeltranoSilva") == "PIX ENVIADO Beltrano Silva"

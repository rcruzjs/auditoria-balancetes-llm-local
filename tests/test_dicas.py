"""Schema linking do chat: dicas sobre onde fica cada nome citado na pergunta (listas fictícias)."""
from web.app import dicas_esquema

CONTAS = [("Natação", "receita"), ("Krav Maga", "receita"), ("Krav Maga", "despesa"), ("Restaurante", "despesa")]
CATEGORIAS = ["Buffet", "Restaurante e alimentação", "Manutenção e obras"]


def test_conta_do_balancete_sem_acento_na_pergunta():
    d = dicas_esquema("Qual a receita de natacao em 2026?", CONTAS, CATEGORIAS)[0]
    assert "v_balancete_selecionado" in d and "string = 'Natação'" in d and "coluna credito" in d


def test_conta_com_duas_naturezas():
    d = dicas_esquema("Quanto gastou e recebeu com Krav Maga?", CONTAS, CATEGORIAS)[0]
    assert "despesa: coluna debito" in d and "receita: coluna credito" in d


def test_categoria():
    d = dicas_esquema("Gasto com manutenção e obras em 2025", CONTAS, CATEGORIAS)[0]
    assert "categoria = 'Manutenção e obras'" in d


def test_nome_contido_em_outro_vale_o_maior():
    dicas = dicas_esquema("Gasto com restaurante e alimentação", CONTAS, CATEGORIAS)
    nomes = [d for d in dicas if "categoria" in d or "conta do balancete" in d]
    assert len(nomes) == 1 and "categoria = 'Restaurante e alimentação'" in nomes[0]


def test_movimentos_financeiros_aponta_a_coluna_string():
    dicas = dicas_esquema("Segundo os movimentos financeiros, total de TED enviado", CONTAS, CATEGORIAS)
    assert any("coluna string" in d and "'TED enviado'" in d and "'Pix recebido'" not in d for d in dicas)


def test_fornecedor_e_saida():
    dicas = dicas_esquema("Quais fornecedores de buffet mais receberam?", CONTAS, CATEGORIAS)
    assert any("valor < 0" in d for d in dicas) and any("categoria = 'Buffet'" in d for d in dicas)


def test_sem_nomes_conhecidos_so_a_dica_de_total():
    (d,) = dicas_esquema("Quantos documentos foram carregados?", CONTAS, CATEGORIAS)
    assert "NÃO pede valores por mês" in d


def test_pedido_mensal():
    for p in ("Gasto com buffet por mês em 2025", "Receita de natação mês a mês", "Valores de cada mês"):
        dicas = dicas_esquema(p, CONTAS, CATEGORIAS)
        assert any("pede valores por mês" in d for d in dicas), p


def test_pergunta_sobre_qual_mes_nao_recebe_dica_de_total():
    dicas = dicas_esquema("Em qual mês o gasto com buffet foi maior?", CONTAS, CATEGORIAS)
    assert not any("por mês" in d for d in dicas)

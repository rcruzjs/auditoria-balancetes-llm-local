"""Site da Auditoria de balancetes: painel, eventos, transações, documentos, pontos de atenção e chat.

Rodar:  .venv/Scripts/python -m uvicorn web.app:app --port 8500
Abrir:  http://127.0.0.1:8500
"""
from __future__ import annotations

import io
import json
import os
import re
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import psycopg
import pymupdf
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter
from pydantic import BaseModel, Field

from pcsf import clube
from pcsf.classificar import sem_acento
from pcsf.db import conectar
from pcsf.llm import chat_json, config

RAIZ = Path(__file__).resolve().parent.parent
PASTA_PDF = RAIZ / "balancetes pcsf"
app = FastAPI(title="Auditoria de balancetes")


# ----------------------------------------------------------------------------- utilidades
CPF = re.compile(r"(?<!\d)(\d{3})(\d{3})(\d{3})(\d{2})(?!\d)")


def mascara(v):
    """LGPD: CPF aparece só parcialmente (***.456.789-**). CNPJ (14 dígitos) fica visível."""
    if isinstance(v, str):
        return CPF.sub(lambda m: f"***.{m.group(2)}.{m.group(3)}-**", v)
    return v


def jsonavel(v):
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    return mascara(v)


def consulta(sql: str, params=(), leitor: bool = False) -> tuple[list[str], list[tuple]]:
    con = psycopg.connect(url_leitor()) if leitor else conectar()
    with con:
        cur = con.execute(sql, params or None)   # sem parâmetros: '%' literal (ex.: ILIKE '%x%' do chat)
        cols = [d.name for d in cur.description] if cur.description else []
        return cols, cur.fetchall() if cur.description else []


def dicts(sql: str, params=()) -> list[dict]:
    cols, rows = consulta(sql, params)
    return [{c: jsonavel(v) for c, v in zip(cols, r)} for r in rows]


def url_leitor() -> str:
    return (f"postgresql://leitor:{os.environ['LEITOR_PASSWORD']}@127.0.0.1:"
            f"{os.environ.get('POSTGRES_PORT', '5433')}/{os.environ.get('POSTGRES_DB', 'auditoria')}")


def excel(cols: list[str], rows: list, nome: str, titulo: str, fonte: str = "") -> Response:
    """Planilha formatada, com uma aba 'Fonte' que diz de onde vieram os números."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Dados"
    ws.append(cols)
    for r in rows:
        ws.append([jsonavel(v) if not isinstance(v, (date, datetime)) else v for v in r])
    for i, c in enumerate(cols, 1):
        cel = ws.cell(row=1, column=i)
        cel.font, cel.fill = Font(bold=True, color="FFFFFF"), PatternFill("solid", fgColor="1F3A5F")
        larg = max([len(str(c))] + [len(str(r[i - 1])) for r in rows[:200]]) + 2
        ws.column_dimensions[get_column_letter(i)].width = min(max(larg, 10), 60)
        if any(isinstance(r[i - 1], (Decimal, float)) for r in rows[:50]):
            for row in ws.iter_rows(min_row=2, min_col=i, max_col=i):
                row[0].number_format = "#,##0.00"
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    f = wb.create_sheet("Fonte")
    for linha in [["Auditoria de balancetes — " + titulo], [f"Gerado em {datetime.now():%d/%m/%Y %H:%M}"],
                  ["Origem: extratos bancários anexos aos balancetes mensais, conferidos com os saldos do banco."],
                  ["CPFs mascarados (LGPD)."], [""], ["Consulta:"], [fonte]]:
        f.append(linha)
    f.column_dimensions["A"].width = 120
    buf = io.BytesIO()
    wb.save(buf)
    return Response(buf.getvalue(), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{nome}.xlsx"'})


# ----------------------------------------------------------------------------- painel
@app.get("/api/painel")
def painel():
    kpi = dicts("""
        SELECT sum(valor) FILTER (WHERE valor > 0) AS entradas, -sum(valor) FILTER (WHERE valor < 0) AS saidas,
               sum(valor) AS resultado, count(*) AS lancamentos,
               -sum(valor) FILTER (WHERE valor < 0 AND categoria_grupo = 'Eventos') AS eventos,
               min(data_mov) AS inicio, max(data_mov) AS fim
        FROM v_movimentos""")[0]
    docs = dicts("SELECT count(*) AS arquivos, count(*) FILTER (WHERE conciliado) AS conciliados, "
                 "sum(cardinality(paginas_ocr)) AS paginas_ocr FROM documentos")[0]
    mensal = dicts("""
        SELECT to_char(mes, 'YYYY-MM') AS mes, entradas, saidas, resultado,
               (SELECT -sum(valor) FROM v_movimentos v WHERE v.mes = r.mes AND v.valor < 0
                  AND v.categoria_grupo = 'Eventos') AS eventos
        FROM v_resumo_mensal r""")
    grupos = dicts("""
        SELECT COALESCE(categoria_grupo, 'Sem categoria') AS grupo, -sum(valor) AS total, count(*) AS n
        FROM v_movimentos WHERE valor < 0 GROUP BY 1 ORDER BY 2 DESC""")
    return {"clube": clube.NOME, "kpi": kpi, "docs": docs, "mensal": mensal, "grupos": grupos}


@app.get("/api/eventos/gastos")
def gastos_eventos():
    por_cat = dicts("""
        SELECT categoria, -sum(valor) AS total, count(*) AS pagamentos, count(DISTINCT contraparte_id) AS recebedores
        FROM v_movimentos WHERE valor < 0 AND categoria_grupo = 'Eventos' GROUP BY 1 ORDER BY 2 DESC""")
    por_mes = dicts("""
        SELECT to_char(mes, 'YYYY-MM') AS mes, categoria, -sum(valor) AS total
        FROM v_movimentos WHERE valor < 0 AND categoria_grupo = 'Eventos' GROUP BY 1, 2 ORDER BY 1""")
    top = dicts("""
        SELECT COALESCE(contraparte_nome, '(sem nome)') AS recebedor, categoria, count(*) AS pagamentos,
               -sum(valor) AS total, min(data_mov) AS primeiro, max(data_mov) AS ultimo,
               round(-sum(valor) / count(*), 2) AS ticket_medio
        FROM v_movimentos WHERE valor < 0 AND categoria_grupo = 'Eventos'
        GROUP BY 1, 2 ORDER BY 4 DESC LIMIT 25""")
    comparativo = dicts("""
        SELECT categoria,
               -sum(valor) FILTER (WHERE data_mov BETWEEN '2025-01-01' AND '2025-06-30') AS s1_2025,
               -sum(valor) FILTER (WHERE data_mov BETWEEN '2026-01-01' AND '2026-06-30') AS s1_2026
        FROM v_movimentos WHERE valor < 0 AND categoria_grupo = 'Eventos' GROUP BY 1 ORDER BY 2 DESC NULLS LAST""")
    return {"por_categoria": por_cat, "por_mes": por_mes, "top": top, "comparativo": comparativo}


# ----------------------------------------------------------------------------- transações
FILTRO_TX = """
FROM v_movimentos
WHERE (%(ini)s::date IS NULL OR data_mov >= %(ini)s::date)
  AND (%(fim)s::date IS NULL OR data_mov <= %(fim)s::date)
  AND (%(tipo)s::text IS NULL OR tipo = %(tipo)s)
  AND (%(grupo)s::text IS NULL OR COALESCE(categoria_grupo, 'Sem categoria') = %(grupo)s)
  AND (%(categoria)s::text IS NULL OR COALESCE(categoria, 'Sem categoria') = %(categoria)s)
  AND (%(direcao)s::text IS NULL OR direcao = %(direcao)s)
  AND (%(q)s::text IS NULL OR descricao ILIKE '%%' || %(q)s || '%%' OR contraparte_nome ILIKE '%%' || %(q)s || '%%')
"""
COLS_TX = ("id, data_mov, conta, tipo, direcao, valor, COALESCE(contraparte_nome, contraparte_doc) AS contraparte, "
           "categoria, categoria_grupo, descricao, documento_id, pagina, origem")


def _filtros(ini, fim, tipo, grupo, categoria, direcao, q):
    return {"ini": ini or None, "fim": fim or None, "tipo": tipo or None, "grupo": grupo or None,
            "categoria": categoria or None, "direcao": direcao or None, "q": (q or "").strip() or None}


@app.get("/api/transacoes")
def transacoes(ini: str = "", fim: str = "", tipo: str = "", grupo: str = "", categoria: str = "",
               direcao: str = "", q: str = "", limite: int = 200, offset: int = 0):
    p = _filtros(ini, fim, tipo, grupo, categoria, direcao, q)
    tot = dicts("SELECT count(*) AS n, sum(valor) AS soma " + FILTRO_TX, p)[0]
    p.update(limite=min(limite, 1000), offset=offset)
    linhas = dicts(f"SELECT {COLS_TX} " + FILTRO_TX + " ORDER BY data_mov DESC, id LIMIT %(limite)s OFFSET %(offset)s", p)
    return {"total": tot, "linhas": linhas}


@app.get("/api/transacoes.xlsx")
def transacoes_xlsx(ini: str = "", fim: str = "", tipo: str = "", grupo: str = "", categoria: str = "",
                    direcao: str = "", q: str = ""):
    p = _filtros(ini, fim, tipo, grupo, categoria, direcao, q)
    sql = f"SELECT {COLS_TX} " + FILTRO_TX + " ORDER BY data_mov, id"
    cols, rows = consulta(sql, p)
    filtro = ", ".join(f"{k}={v}" for k, v in p.items() if v) or "sem filtro"
    return excel(cols, rows, "transacoes", "Transações", f"Filtros: {filtro}")


@app.get("/api/opcoes")
def opcoes():
    return {"tipos": [r["tipo"] for r in dicts("SELECT DISTINCT tipo FROM v_movimentos ORDER BY 1")],
            "categorias": dicts("SELECT nome, grupo FROM categorias ORDER BY grupo, nome")}


# ----------------------------------------------------------------------------- documentos e PDF
@app.get("/api/documentos")
def documentos():
    return dicts("""
        SELECT d.id, d.arquivo, to_char(d.competencia, 'YYYY-MM') AS competencia, d.paginas,
               cardinality(d.paginas_extrato) AS paginas_extrato, cardinality(d.paginas_ocr) AS paginas_ocr,
               d.lancamentos, d.duplicados, d.conciliado, d.status, d.carregado_em,
               (SELECT count(*) FROM conciliacoes c WHERE c.documento_id = d.id) AS conferencias,
               (SELECT count(*) FILTER (WHERE ok) FROM conciliacoes c WHERE c.documento_id = d.id) AS conferencias_ok,
               (SELECT string_agg(DISTINCT conta, ', ') FROM transacoes t WHERE t.documento_id = d.id) AS contas
        FROM documentos d ORDER BY d.competencia""")


@app.get("/api/documentos/{doc_id}/pagina/{pagina}.png")
def pagina_png(doc_id: int, pagina: int, y: float | None = None):
    """Página do PDF original como imagem, com a linha do lançamento destacada (y em pontos PDF)."""
    r = dicts("SELECT arquivo FROM documentos WHERE id = %s", (doc_id,))
    if not r:
        raise HTTPException(404, "documento não encontrado")
    caminho = PASTA_PDF / r[0]["arquivo"]
    with pymupdf.open(caminho) as pdf:
        if not 1 <= pagina <= pdf.page_count:
            raise HTTPException(404, "página inexistente")
        pg = pdf[pagina - 1]
        if y is not None:
            ret = pymupdf.Rect(20, y - 3, pg.rect.width - 20, y + 11)
            pg.draw_rect(ret, color=(0.92, 0.41, 0.2), fill=(1, 0.85, 0.3), fill_opacity=0.35, width=1.2)
        png = pg.get_pixmap(dpi=110).tobytes("png")
    return Response(png, media_type="image/png")


@app.get("/api/transacoes/{tx_id}")
def transacao(tx_id: int):
    r = dicts("""SELECT t.*, d.arquivo, c.nome AS categoria FROM transacoes t JOIN documentos d ON d.id = t.documento_id
                 LEFT JOIN categorias c ON c.id = t.categoria_id WHERE t.id = %s""", (tx_id,))
    if not r:
        raise HTTPException(404)
    return r[0]


# ----------------------------------------------------------------------------- balancete e movimentos selecionados
MES_ANO = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


@app.get("/api/balancete")
def balancete(natureza: str = "receita", coluna: str = "auto", ini: str = "", fim: str = ""):
    """Contas da lista (balancete_filtros) mês a mês: tabela conta × mês.
    coluna 'auto': crédito para receitas, débito para despesas (o valor do mês em cada caso).
    ini/fim (AAAA-MM, opcionais): um mês (ini = fim) ou um intervalo de meses; o total soma só o período."""
    if natureza not in ("receita", "despesa"):
        raise HTTPException(400, "natureza inválida")
    if coluna == "auto":
        coluna = "credito" if natureza == "receita" else "debito"
    if coluna not in ("credito", "debito", "saldo_atual"):
        raise HTTPException(400, "coluna inválida")
    if (ini and not MES_ANO.match(ini)) or (fim and not MES_ANO.match(fim)):
        raise HTTPException(400, "mês/ano inválido (use AAAA-MM)")
    if ini and fim and ini > fim:
        ini, fim = fim, ini
    todos = [r["m"] for r in dicts("SELECT DISTINCT to_char(competencia, 'YYYY-MM') AS m FROM balancete ORDER BY 1")]
    meses = [m for m in todos if (not ini or m >= ini) and (not fim or m <= fim)]
    p = {"nat": natureza, "ini": f"{ini}-01" if ini else None, "fim": f"{fim}-01" if fim else None}
    linhas = dicts(f"""SELECT f.ordem, f.codigo, COALESCE(max(v.string), f.descricao) AS string, max(v.tipo) AS tipo,
                              max(v.grupo) AS grupo, json_object_agg(to_char(v.competencia, 'YYYY-MM'), v.{coluna})
                                FILTER (WHERE v.competencia IS NOT NULL) AS valores,
                              sum(v.{coluna}) AS total
                       FROM balancete_filtros f
                       LEFT JOIN v_balancete_selecionado v ON v.codigo = f.codigo
                            AND (%(ini)s::date IS NULL OR v.competencia >= %(ini)s::date)
                            AND (%(fim)s::date IS NULL OR v.competencia <= %(fim)s::date)
                       WHERE f.ativo AND f.natureza = %(nat)s GROUP BY 1, 2, f.descricao ORDER BY 1""", p)
    for l in linhas:
        l["valores"] = {k: float(v) for k, v in (l["valores"] or {}).items() if v is not None}
    conferencia = dicts("""SELECT count(*) AS meses, count(*) FILTER (WHERE ok) AS ok FROM conciliacoes WHERE tipo = 'balancete'""")[0]
    return {"meses": meses, "todos_meses": todos, "ini": ini or None, "fim": fim or None, "linhas": linhas,
            "coluna": coluna, "natureza": natureza, "conferencia": conferencia}


@app.get("/api/movimentos")
def movimentos(string: str = "", mes: str = "", q: str = "", limite: int = 300, offset: int = 0):
    p = {"s": string or None, "m": mes or None, "q": (q or "").strip() or None,
         "lim": min(limite, 1000), "off": offset}
    filtro = """FROM movimentos_financeiros WHERE (%(s)s::text IS NULL OR string = %(s)s)
                AND (%(m)s::text IS NULL OR mes_ano = %(m)s)
                AND (%(q)s::text IS NULL OR favorecido ILIKE '%%' || %(q)s || '%%' OR historico ILIKE '%%' || %(q)s || '%%')"""
    tot = dicts("SELECT count(*) AS n, sum(valor) AS soma " + filtro, p)[0]
    resumo = dicts("SELECT string, count(*) AS n, sum(valor) AS total, count(*) FILTER (WHERE interno) AS internos "
                   + filtro + " GROUP BY 1 ORDER BY 1", p)
    linhas = dicts("""SELECT id, relatorio, pagina, mes_ano, data_mov, string, valor, favorecido, papel, variante,
                             interno, historico """ + filtro + " ORDER BY data_mov DESC, id LIMIT %(lim)s OFFSET %(off)s", p)
    return {"total": tot, "resumo": resumo, "linhas": linhas}


@app.get("/api/relatorios/{nome}.xlsx")
def relatorio(nome: str, ini: str = "", fim: str = ""):
    from pcsf import relatorios
    if (ini and not MES_ANO.match(ini)) or (fim and not MES_ANO.match(fim)):
        raise HTTPException(400, "mês/ano inválido (use AAAA-MM)")
    if ini and fim and ini > fim:
        ini, fim = fim, ini
    if nome == "balancete_selecionado":
        arq = relatorios.balancete(ini or None, fim or None)
    elif nome == "movimentos_financeiros":
        arq = relatorios.movimentos()
    else:
        raise HTTPException(404)
    return FileResponse(arq, filename=arq.name,
                        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


# ----------------------------------------------------------------------------- eventos
class Evento(BaseModel):
    nome: str = Field(min_length=2, max_length=200)
    data_inicio: date
    data_fim: date | None = None
    tipo: str | None = None
    local: str | None = None
    publico_estimado: int | None = None
    link_instagram: str | None = None
    observacoes: str | None = None


@app.get("/api/eventos")
def eventos_lista():
    return dicts("SELECT * FROM eventos ORDER BY data_inicio DESC")


@app.post("/api/eventos")
def evento_criar(e: Evento):
    _, rows = consulta(
        """INSERT INTO eventos (nome, data_inicio, data_fim, tipo, local, publico_estimado, link_instagram, observacoes)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
        (e.nome, e.data_inicio, e.data_fim, e.tipo, e.local, e.publico_estimado, e.link_instagram, e.observacoes))
    return {"id": rows[0][0]}


@app.delete("/api/eventos/{ev_id}")
def evento_apagar(ev_id: int):
    consulta("DELETE FROM eventos WHERE id = %s RETURNING id", (ev_id,))
    return {"ok": True}


@app.get("/api/eventos/{ev_id}/cruzamento")
def cruzamento(ev_id: int, antes: int = 30, depois: int = 7):
    """Gastos com categorias de eventos na janela [início - antes, fim + depois] e receitas de aluguel/eventos."""
    ev = dicts("SELECT * FROM eventos WHERE id = %s", (ev_id,))
    if not ev:
        raise HTTPException(404)
    p = {"id": ev_id, "antes": antes, "depois": depois}
    janela = """(SELECT data_inicio - %(antes)s * interval '1 day' FROM eventos WHERE id = %(id)s)
                AND (SELECT COALESCE(data_fim, data_inicio) + %(depois)s * interval '1 day' FROM eventos WHERE id = %(id)s)"""
    gastos = dicts(f"""SELECT id, data_mov, COALESCE(contraparte_nome, '(sem nome)') AS recebedor, categoria, valor,
                              descricao, documento_id, pagina
                       FROM v_movimentos WHERE valor < 0 AND categoria_grupo = 'Eventos'
                         AND data_mov BETWEEN {janela} ORDER BY data_mov""", p)
    total = sum(-g["valor"] for g in gastos)
    return {"evento": ev[0], "janela": {"antes": antes, "depois": depois}, "gastos": gastos, "total_gastos": total}


# ----------------------------------------------------------------------------- pontos de atenção
@app.get("/api/alertas")
def alertas():
    """Padrões que merecem esclarecimento. Não são acusações: são perguntas a fazer à diretoria."""
    out = []
    sicredi = dicts("""SELECT data_mov, conta, valor, descricao, id, documento_id, pagina FROM transacoes
                       WHERE duplicada_de IS NULL AND strpos(descricao, %s) > 0 ORDER BY data_mov""",
                    (clube.SICREDI_PADRAO,)) if clube.SICREDI_PADRAO else []
    contabil_sicredi = dicts("""
        SELECT to_char(competencia, 'YYYY-MM') AS mes, descricao AS conta_contabil, debito AS entradas, credito AS saidas,
               saldo_atual AS saldo, saldo_atual_nat AS nat
        FROM balancete WHERE tipo = 'conta' AND descricao ILIKE 'Sicred - %%' ORDER BY competencia, codigo""")
    if sicredi:
        out.append({"nivel": "alto", "titulo": "Extratos das contas do clube no Sicredi não estão nos balancetes",
                    "valor": sum(-x["valor"] for x in sicredi), "n": len(sicredi),
                    "texto": "O balancete registra, desde jan/2026, contas do clube no Sicredi (movimento, provisão e "
                             "fundo de reserva). As TEDs do Santander para elas são "
                             "transferências internas (não são gastos), mas os extratos do Sicredi não são anexados: "
                             "o que entra e sai dessas contas não pode ser conferido. Pedir os extratos.",
                    "itens": sicredi})
        out.append({"nivel": "alto", "titulo": "Movimentação das contas do Sicredi segundo a contabilidade",
                    "texto": "Débito = entrada na conta; crédito = saída. É tudo o que se sabe dessas contas sem o extrato.",
                    "itens": contabil_sicredi})
    queda = dicts("""SELECT to_char(mes, 'YYYY-MM') AS mes, sum(valor) FILTER (WHERE tipo = 'COBRANCA_RECEBIDA') AS cobrancas
                     FROM v_movimentos WHERE mes >= '2026-01-01' GROUP BY 1 ORDER BY 1""")
    out.append({"nivel": "alto", "titulo": "Cobranças de mensalidade somem do Santander a partir de mai/2026",
                "texto": "As cobranças recebidas no Santander caem bruscamente a partir de maio (veja a tabela; "
                         "o banco confirma os totais). Provavelmente passaram para o Sicredi, cujos extratos não estão "
                         "nos balancetes.", "itens": queda})
    mapa = clube.CONTAS_BALANCETE   # conta contábil -> conta bancária
    conc = dicts("""
        WITH mapa (codigo, conta) AS (SELECT * FROM unnest(%s::text[], %s::text[])),
        contabil AS (
            SELECT b.competencia, m.conta, b.debito, b.credito FROM balancete b JOIN mapa m USING (codigo)),
        banco AS (
            SELECT competencia, conta, COALESCE(sum(valor) FILTER (WHERE valor > 0), 0) AS ent,
                   COALESCE(-sum(valor) FILTER (WHERE valor < 0), 0) AS sai
            FROM transacoes WHERE duplicada_de IS NULL GROUP BY 1, 2)
        SELECT to_char(c.competencia, 'YYYY-MM') AS mes, c.conta, c.debito AS contabil_entradas,
               COALESCE(b.ent, 0) AS extrato_entradas, c.debito - COALESCE(b.ent, 0) AS diferenca_entradas,
               c.credito AS contabil_saidas, COALESCE(b.sai, 0) AS extrato_saidas, c.credito - COALESCE(b.sai, 0) AS diferenca_saidas
        FROM contabil c LEFT JOIN banco b USING (competencia, conta)
        WHERE c.debito <> COALESCE(b.ent, 0) OR c.credito <> COALESCE(b.sai, 0)
        ORDER BY 1, 2""", (list(mapa), list(mapa.values()))) if mapa else []
    meses_ok = dicts("SELECT count(DISTINCT competencia) AS n FROM balancete WHERE codigo = %s",
                     (next(iter(mapa)),))[0]["n"] if mapa else 0
    out.append({"nivel": "baixo", "titulo": "Contabilidade × extrato: pequenas diferenças em alguns meses",
                "n": len(conc), "unidade": "conta-mês com diferença",
                "texto": f"A conta contábil de cada conta bancária foi comparada com o extrato nos {meses_ok} meses. "
                         "Onde há diferença, ela é igual em entradas e saídas: pares de lançamentos de ida e volta "
                         "(ex.: estornos) que o banco mostra e a contabilidade compensou. O saldo não muda. "
                         "Vale pedir ao contador a explicação de cada caso.", "itens": conc})
    pagfor = dicts("""SELECT to_char(mes, 'YYYY-MM') AS mes, count(*) AS pagamentos, -sum(valor) AS total
                      FROM v_movimentos WHERE tipo = 'PAGFOR_LOTE' GROUP BY 1 ORDER BY 1""")
    out.append({"nivel": "medio", "titulo": "Pagamentos em lote (PAGFOR) sem nome do recebedor",
                "valor": sum(x["total"] for x in pagfor), "n": sum(x["pagamentos"] for x in pagfor),
                "texto": "O extrato mostra só o número do convênio. Para saber quem recebeu, pedir os relatórios "
                         "de remessa/retorno do PAGFOR.", "itens": pagfor})
    repetidos = dicts("""
        SELECT a.data_mov AS data_1, b.data_mov AS data_2, a.contraparte_nome AS recebedor, -a.valor AS valor,
               a.id AS id_1, b.id AS id_2, a.documento_id, a.pagina
        FROM v_movimentos a JOIN v_movimentos b
          ON a.contraparte_id = b.contraparte_id AND a.valor = b.valor AND a.id < b.id
         AND b.data_mov BETWEEN a.data_mov AND a.data_mov + 7
        WHERE a.valor <= -1000 AND a.tipo NOT IN ('FOLHA', 'TRIBUTO', 'TARIFA')
        ORDER BY a.valor LIMIT 60""")
    out.append({"nivel": "medio", "titulo": "Mesmo valor, mesmo recebedor, em até 7 dias (acima de R$ 1 mil)",
                "valor": sum(x["valor"] for x in repetidos), "n": len(repetidos), "unidade": "pares",
                "texto": "Pode ser parcelamento combinado ou pagamento em duplicidade. Conferir com as notas.",
                "itens": repetidos})
    saques = dicts("""SELECT to_char(mes, 'YYYY-MM') AS mes, count(*) AS n, -sum(valor) AS total
                      FROM v_movimentos WHERE tipo = 'CHEQUE_SAQUE' GROUP BY 1 ORDER BY 1""")
    out.append({"nivel": "baixo", "titulo": "Cheques e saques em dinheiro",
                "valor": sum(x["total"] for x in saques), "n": sum(x["n"] for x in saques),
                "texto": "Saídas sem destinatário identificado no extrato.", "itens": saques})
    return out


# ----------------------------------------------------------------------------- chat (pergunta -> SQL -> resposta)
ESQUEMA = """Tabela/visão principal: v_movimentos (lançamentos bancários reais, sem duplicatas nem transferências internas)
colunas: id, data_mov date, mes date (1º dia do mês), conta text, tipo text, direcao char(1) ('E' entrada, 'S' saída),
valor numeric (entrada > 0, saída < 0), contraparte_nome text (nome do recebedor, até 25 caracteres),
contraparte_doc text (CPF/CNPJ quando houver), categoria text, categoria_grupo text, descricao text (histórico do banco),
documento_id int, pagina int.
Valores de tipo: PIX_RECEBIDO, PIX_ENVIADO, BOLETO, TED_ENVIADA, TED_RECEBIDA, PAGFOR_LOTE, FOLHA, COBRANCA_RECEBIDA,
CARTAO, CHEQUE_SAQUE, TARIFA, TRIBUTO, CONTA_CONSUMO, DEPOSITO, TRANSF_TERCEIRO, OUTROS.
Grupos de categoria: Eventos, Pessoal, Operacional, Receitas (NULL = sem categoria).
Categorias de v_movimentos (as ÚNICAS que existem; filtre com categoria = '<nome exato>'): {{CATEGORIAS}}
Balancete contábil (separado dos extratos): v_balancete_selecionado(relatorio, mes_ano text 'MM/AAAA', competencia date,
codigo, string text (nome da conta, ex.: 'Aluguel de Salão', 'Carnaval', 'Natação'), tipo ('conta' ou 'grupo'),
grupo text, debito numeric, credito numeric, saldo_atual numeric, natureza text ('receita' ou 'despesa')).
Em contas de receita, o crédito é a receita do mês; em contas de despesa, o débito é o gasto do mês.
Movimentos selecionados dos extratos: movimentos_financeiros(relatorio, pagina, mes_ano, competencia, data_mov,
string ('Pix recebido','Saque dinheiro','Pagamento fornecedor','Cheque emitido','TED enviado','Pix enviado',
'Dep cheque','TAR'), valor, favorecido, papel, interno boolean, historico).
Outras tabelas: eventos(id, nome, data_inicio, data_fim, tipo, local, publico_estimado),
documentos(id, arquivo, competencia date, paginas, lancamentos, conciliado).
Período dos dados: jan/2025 a jun/2026."""

SYSTEM_SQL = f"""Você traduz perguntas em português sobre as finanças de um clube para UMA consulta SQL PostgreSQL.
{ESQUEMA}
Regras:
- Somente SELECT (ou WITH ... SELECT). Nunca altere dados.
- Gastos são valores negativos: para mostrar gasto positivo use -sum(valor).
- Use ILIKE para buscar nomes. Datas no formato 'AAAA-MM-DD'.
- Limite listas a 100 linhas. Arredonde valores com round(..., 2). Dê nomes claros às colunas, em português.
- Não faça contas fora do SQL.
- Agrupe e ordene pela posição (GROUP BY 1, ORDER BY 1). Nunca dê a um apelido o nome de uma coluna existente
  (ex.: não use "AS mes"; use "AS mes_ref").
- Para gastos, filtre valor < 0. Para receitas, valor > 0.
- Nomes de recebedores e históricos: busque sem acento, unaccent(coluna) ILIKE unaccent('%texto%').
  Categorias e contas do balancete: use = com o nome exato das listas, com acentos normais.
  Nunca codifique texto como URL (errado: '%C3%A7').
- Para filtrar período use as colunas de data (data_mov ou competencia) com BETWEEN, nunca o texto mes_ano.
- Receitas de aluguéis (salão, boate, churrasqueira, tenda, estacionamento), escolinhas, festas, carnaval, náutica,
  tênis, natação e demais atividades: use v_balancete_selecionado com natureza = 'receita' e a coluna credito.
- Despesas contábeis por diretoria ou conta (Festa Junina, Música ao Vivo, Dia das Mães, Aniversário Clube, manutenção,
  patrimônio, piscina, náutica, futebol, informática, conselho...): use v_balancete_selecionado com
  natureza = 'despesa' e a coluna debito.
- v_balancete_selecionado tem a coluna natureza ('receita' ou 'despesa'). Sempre filtre a natureza, porque alguns nomes
  existem nas duas (Krav Maga, Beach Tennis, Hidroginástica, Diretoria Social e Cultural).
  Filtre string = '<nome exato>'. {{{{CONTAS}}}}
- Pagamentos a fornecedores e gastos com eventos: use v_movimentos.
- Escolha da fonte: se a pergunta cita o nome de uma conta da lista de contas do balancete (ex.: Natação,
  Música ao Vivo, Torneio de Futebol), use v_balancete_selecionado, mesmo que a pergunta não diga "balancete".
  Se cita "movimentos financeiros", use movimentos_financeiros com string = '<nome exato>' (saída < 0, entrada > 0).
- Direção: pagamentos feitos pelo clube, recebedores e fornecedores são SAÍDAS (valor < 0; mostre -sum(valor)).
  Dinheiro que o clube recebeu são ENTRADAS (valor > 0).
- Total ou mês a mês: só agrupe por mês se a pergunta pedir "por mês", "cada mês" ou "mês a mês".
  "Quanto foi gasto/recebido em 2025" é UMA linha com o total do período.
- Comparar períodos: UMA consulta, sem UNION, com uma coluna por período usando
  sum(...) FILTER (WHERE <coluna de data> BETWEEN ...).
- No balancete, linhas de total de grupo têm tipo = 'grupo'. "Somente contas" ou "sem grupos": filtre tipo = 'conta'.

Exemplos:
Pergunta: Quanto foi gasto com bebidas por mês em 2025?
{{"sql": "SELECT to_char(mes, 'YYYY-MM') AS mes_ref, round(-sum(valor), 2) AS total_gasto FROM v_movimentos WHERE valor < 0 AND categoria = 'Bebidas' AND data_mov BETWEEN '2025-01-01' AND '2025-12-31' GROUP BY 1 ORDER BY 1", "explicacao": "Soma das saídas da categoria Bebidas em cada mês de 2025."}}
Pergunta: Quais os 5 maiores fornecedores de eventos?
{{"sql": "SELECT contraparte_nome AS fornecedor, categoria, count(*) AS pagamentos, round(-sum(valor), 2) AS total_pago FROM v_movimentos WHERE valor < 0 AND categoria_grupo = 'Eventos' GROUP BY 1, 2 ORDER BY 4 DESC LIMIT 5", "explicacao": "Fornecedores com maior soma de pagamentos em categorias de eventos."}}
Pergunta: Quanto o clube recebeu de aluguel de churrasqueira por mês em 2025, segundo o balancete?
{{"sql": "SELECT to_char(competencia, 'YYYY-MM') AS mes_ref, string AS conta, round(sum(credito), 2) AS credito FROM v_balancete_selecionado WHERE string = 'Churrasqueiras - Aluguel' AND competencia BETWEEN '2025-01-01' AND '2025-12-31' GROUP BY 1, 2 ORDER BY 1", "explicacao": "Crédito (receita) mensal da conta contábil de aluguel de churrasqueiras em 2025."}}
Pergunta: Quanto o clube gastou e quanto recebeu com Beach Tennis em 2025?
{{"sql": "SELECT natureza, round(sum(CASE WHEN natureza = 'receita' THEN credito ELSE debito END), 2) AS total FROM v_balancete_selecionado WHERE string = 'Beach Tennis' AND competencia BETWEEN '2025-01-01' AND '2025-12-31' GROUP BY 1 ORDER BY 1", "explicacao": "Total de 2025 da conta Beach Tennis como receita (crédito) e como despesa (débito)."}}
Pergunta: Compare o gasto com tarifas bancárias de 2025 com o de 2026.
{{"sql": "SELECT round(-sum(valor) FILTER (WHERE data_mov BETWEEN '2025-01-01' AND '2025-12-31'), 2) AS gasto_2025, round(-sum(valor) FILTER (WHERE data_mov BETWEEN '2026-01-01' AND '2026-12-31'), 2) AS gasto_2026 FROM v_movimentos WHERE valor < 0 AND categoria = 'Tarifas bancárias'", "explicacao": "Total de tarifas bancárias em 2025 e em 2026, lado a lado."}}
Pergunta: Quanto pagamos à empresa X?
{{"sql": "SELECT contraparte_nome AS recebedor, count(*) AS pagamentos, round(-sum(valor), 2) AS total_pago, min(data_mov) AS primeiro, max(data_mov) AS ultimo FROM v_movimentos WHERE valor < 0 AND (contraparte_nome ILIKE '%X%' OR descricao ILIKE '%X%') GROUP BY 1 ORDER BY 3 DESC LIMIT 100", "explicacao": "Pagamentos a recebedores cujo nome contém X."}}

Responda só JSON: {{"sql": "<consulta>", "explicacao": "<uma frase dizendo o que a consulta calcula>"}}"""

SYSTEM_RESPOSTA = """Você responde em português, em no máximo 4 frases, com base SOMENTE no resultado da consulta abaixo.
Não invente números: cite apenas os que aparecem no resultado, exatamente como estão. NUNCA some, subtraia,
calcule médias ou percentuais: se um total não estiver no resultado, diga que os valores estão na tabela.
Valores em reais no formato R$ 1.234,56.
Se o resultado estiver vazio, diga que não há dados para a pergunta.
Responda só JSON: {"resposta": "<texto>"}"""

PROIBIDO = re.compile(r"\b(insert|update|delete|drop|alter|create|grant|revoke|truncate|copy|call|vacuum|"
                      r"pg_sleep|pg_read|lo_import|set\s+role)\b", re.I)


NUMERO = re.compile(r"\d{1,3}(?:\.\d{3})+(?:,\d{1,2})?|\d+,\d{1,2}|\d{4,}")


def numeros_conferem(texto: str, linhas: list) -> bool:
    """Trava contra conta errada do LLM: todo valor citado na resposta (>= 100 ou com centavos)
    tem de existir no resultado da consulta. Anos soltos (2025, 2026) são ignorados."""
    no_resultado = set()
    for linha in linhas:
        for v in linha:
            if isinstance(v, (int, float)):
                no_resultado.add(round(abs(float(v)), 2))
            elif isinstance(v, str):
                for m in NUMERO.findall(v):
                    no_resultado.add(round(float(m.replace(".", "").replace(",", ".")), 2))
    for m in NUMERO.findall(texto):
        n = round(float(m.replace(".", "").replace(",", ".")), 2)
        if "," not in m and "." not in m and 1990 <= n <= 2100:
            continue
        if n >= 100 and n not in no_resultado:
            return False
    return True


def system_sql() -> str:
    """Prompt do SQL com os nomes exatos das contas acompanhadas (o modelo de 8B erra nomes e acentos)."""
    contas = dicts("SELECT natureza, string_agg(descricao, '; ' ORDER BY ordem) AS nomes FROM balancete_filtros "
                   "WHERE ativo GROUP BY 1 ORDER BY 1 DESC")
    texto = " ".join(f"Contas de {c['natureza']}: {c['nomes']}." for c in contas)
    cats = dicts("SELECT grupo, string_agg(nome, ', ' ORDER BY nome) AS nomes FROM categorias GROUP BY 1 ORDER BY 1")
    categorias = "; ".join(f"{c['grupo']}: {c['nomes']}" for c in cats) + "."
    return SYSTEM_SQL.replace("{{CONTAS}}", texto).replace("{{CATEGORIAS}}", categorias)


class Pergunta(BaseModel):
    pergunta: str = Field(min_length=3, max_length=500)


def _sql_seguro(sql: str) -> str:
    sql = sql.strip().rstrip(";")
    if ";" in sql or PROIBIDO.search(sql) or not re.match(r"^\s*(with|select)\b", sql, re.I):
        raise HTTPException(400, "A consulta gerada não é uma leitura simples; reformule a pergunta.")
    if not re.search(r"\blimit\s+\d+", sql, re.I):
        sql += " LIMIT 500"
    return sql


STRINGS_MOV_FIN = ("Pix recebido", "Saque dinheiro", "Pagamento fornecedor", "Cheque emitido", "TED enviado",
                   "Pix enviado", "Dep cheque", "TAR")


def _norm(s: str) -> str:
    return " ".join(sem_acento(s).lower().split())


def dicas_esquema(pergunta: str, contas: list[tuple[str, str]], categorias: list[str]) -> list[str]:
    """Schema linking: acha na pergunta nomes de contas do balancete e de categorias que existem de fato e diz ao
    modelo onde cada um fica (o 8B confunde os dois mesmo com as listas no prompt). Se um nome citado está contido
    em outro também citado (conta 'Restaurante' dentro da categoria 'Restaurante e alimentação'), vale o maior."""
    q = _norm(pergunta)
    achados: dict[str, list[str]] = {}
    naturezas: dict[str, tuple[str, set]] = {}
    for nome, natureza in contas:
        n = _norm(nome)
        if len(n) >= 4 and re.search(rf"\b{re.escape(n)}\b", q):
            naturezas.setdefault(n, (nome, set()))[1].add(natureza)
    for n, (nome, nats) in naturezas.items():
        colunas = " / ".join(f"{x}: coluna {'credito' if x == 'receita' else 'debito'}" for x in sorted(nats))
        achados.setdefault(n, []).append(f"'{nome}' é conta do balancete: use v_balancete_selecionado com "
                                         f"string = '{nome}' e natureza ({colunas}).")
    for nome in categorias:
        n = _norm(nome)
        if re.search(rf"\b{re.escape(n)}\b", q):
            achados.setdefault(n, []).append(f"'{nome}' é categoria dos extratos: use v_movimentos com categoria = '{nome}'.")
    dicas = [d for n, ds in achados.items() if not any(n != m and n in m for m in achados) for d in ds]
    if "movimentos financeiros" in q:
        citadas = [s for s in STRINGS_MOV_FIN if re.search(rf"\b{re.escape(_norm(s))}\b", q)]
        dicas.append("Use movimentos_financeiros; o tipo do movimento fica na coluna string, com um destes valores: "
                     + ", ".join(f"'{s}'" for s in (citadas or STRINGS_MOV_FIN)) + ".")
    if re.search(r"\b(fornecedor(es)?|recebedor(es)?)\b", q):
        dicas.append("Fornecedores e recebedores recebem pagamentos FEITOS pelo clube: são saídas (valor < 0); "
                     "mostre o total com -sum(valor).")
    if re.search(r"\b(por mes|cada mes|mes a mes|mensal(mente)?)\b", q):
        dicas.append("A pergunta pede valores por mês: agrupe por to_char(<coluna de data>, 'YYYY-MM').")
    elif not re.search(r"\b(qual|que|em que) mes\b", q):
        dicas.append("A pergunta NÃO pede valores por mês: não agrupe por mês; some o período inteiro "
                     "(uma linha de total, ou uma linha por item quando a pergunta lista itens).")
    return dicas


def _com_dicas(pergunta: str) -> str:
    contas = [(r["descricao"], r["natureza"]) for r in dicts("SELECT descricao, natureza FROM balancete_filtros WHERE ativo")]
    categorias = [r["nome"] for r in dicts("SELECT nome FROM categorias")]
    dicas = dicas_esquema(pergunta, contas, categorias)
    return pergunta + ("\n\nDicas do esquema (confiáveis, siga-as):\n" + "\n".join(f"- {d}" for d in dicas) if dicas else "")


def gerar_sql(pergunta: str, url: str | None = None, modelo: str | None = None) -> dict:
    """Pergunta -> SQL (LLM) -> execução como 'leitor', com uma correção automática se o SQL falhar.
    Usada pelo chat e pelo benchmark (avaliacao/benchmark.py), para que os dois meçam o mesmo caminho."""
    erro, sql, cols, rows, segundos, corrigido = None, None, [], [], 0.0, False
    system = system_sql()
    pergunta = _com_dicas(pergunta)
    gerado, s = chat_json(system, pergunta, url=url, modelo=modelo)
    segundos += s
    for tentativa in range(2):
        try:
            sql = _sql_seguro(gerado.get("sql", ""))
            cols, rows = consulta(sql, leitor=True)
            erro = None
            break
        except psycopg.Error as e:
            erro = str(e).split("\n")[0]
            if tentativa == 0:   # uma correção automática, mostrando o erro ao modelo
                gerado, s = chat_json(system, f"{pergunta}\n\nA consulta anterior falhou:\n{sql}\nErro: {erro}",
                                      url=url, modelo=modelo)
                segundos += s
                corrigido = True
    return {"sql": sql, "cols": cols, "rows": rows, "erro": erro, "gerado": gerado,
            "corrigido": corrigido, "segundos": segundos}


@app.post("/api/chat")
def chat(p: Pergunta):
    url, modelo = config()
    g = gerar_sql(p.pergunta)
    sql, cols, rows, erro, gerado = g["sql"], g["cols"], g["rows"], g["erro"], g["gerado"]
    linhas = [[jsonavel(v) for v in r] for r in rows]
    resposta, verificada = None, None
    if not erro and all(v is None for l in linhas for v in l):   # nenhuma linha, ou só valores nulos
        verificada = True
        resposta = ("A consulta não encontrou nenhuma linha. Pode ser falta de dados ou um filtro errado do modelo: "
                    "confira o SQL abaixo e, se preciso, reformule a pergunta usando o nome exato da conta ou do fornecedor.")
    elif not erro:
        amostra = json.dumps({"colunas": cols, "linhas": linhas[:30], "total_linhas": len(linhas)}, ensure_ascii=False)
        for _ in range(2):
            r, _ = chat_json(SYSTEM_RESPOSTA, f"Pergunta: {p.pergunta}\n\nResultado:\n{amostra}")
            resposta = r.get("resposta")
            verificada = numeros_conferem(resposta or "", linhas[:30])
            if verificada:
                break
        if not verificada:   # o modelo citou número que não está no resultado: não mostrar a frase
            resposta = f"O resultado está na tabela abaixo ({len(linhas)} linhas)."
    _, ids = consulta("""INSERT INTO consultas_log (pergunta, sql_gerado, modelo, linhas, erro)
                         VALUES (%s, %s, %s, %s, %s) RETURNING id""", (p.pergunta, sql, modelo, len(rows), erro))
    return {"id": ids[0][0], "pergunta": p.pergunta, "sql": sql, "explicacao": gerado.get("explicacao"),
            "colunas": cols, "linhas": linhas[:500], "resposta": resposta, "verificada": verificada,
            "erro": erro, "modelo": modelo}


@app.get("/api/chat/{consulta_id}.xlsx")
def chat_xlsx(consulta_id: int):
    """Reexecuta a consulta registrada (somente leitura) e devolve em Excel."""
    log = dicts("SELECT pergunta, sql_gerado FROM consultas_log WHERE id = %s AND erro IS NULL", (consulta_id,))
    if not log or not log[0]["sql_gerado"]:
        raise HTTPException(404)
    cols, rows = consulta(_sql_seguro(log[0]["sql_gerado"]), leitor=True)
    return excel(cols, rows, f"consulta_{consulta_id}", log[0]["pergunta"], log[0]["sql_gerado"])


@app.get("/api/chat/{consulta_id}.txt")
def chat_txt(consulta_id: int):
    log = dicts("SELECT pergunta, sql_gerado FROM consultas_log WHERE id = %s AND erro IS NULL", (consulta_id,))
    if not log:
        raise HTTPException(404)
    cols, rows = consulta(_sql_seguro(log[0]["sql_gerado"]), leitor=True)
    linhas = ["\t".join(cols)] + ["\t".join(str(jsonavel(v)) for v in r) for r in rows]
    corpo = f"# {log[0]['pergunta']}\n# SQL: {log[0]['sql_gerado']}\n\n" + "\n".join(linhas)
    return Response(corpo, media_type="text/plain; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="consulta_{consulta_id}.txt"'})


# ----------------------------------------------------------------------------- arquivos estáticos
app.mount("/static", StaticFiles(directory=RAIZ / "web" / "static"), name="static")


@app.get("/")
def index():
    return FileResponse(RAIZ / "web" / "static" / "index.html")

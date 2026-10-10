"""Revisão das categorias em Excel: exporta as sugestões do LLM e importa a decisão final.

Uso:
    python -m pcsf.revisao exportar     # gera saidas/revisao_categorias.xlsx
    python -m pcsf.revisao importar     # lê a coluna "Categoria final" e aplica no banco

Na planilha: "S" na coluna "Aceitar?" confirma a sugestão do LLM; ou escolha outra categoria em "Categoria final"
(ela tem prioridade). Deixe em branco o que não quiser decidir agora. A categoria vale para todos os pagamentos
do recebedor. Nada vem pré-preenchido: o LLM erra com confiança alta (ex.: Magazine Luiza -> alimentação).
"""
from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.formatting.rule import CellIsRule
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

from .db import conectar

ARQ = Path(__file__).resolve().parent.parent / "saidas" / "revisao_categorias.xlsx"

SQL = """
WITH ult AS (
    SELECT DISTINCT ON (contraparte_id) * FROM sugestoes_categoria ORDER BY contraparte_id, criado_em DESC
)
SELECT cp.id, COALESCE(cp.nome_extrato, cp.chave) AS recebedor, cp.tipo, cp.documento,
       count(t.*) AS pagamentos, round(-sum(t.valor), 2) AS total,
       to_char(min(t.data_mov), 'MM/YYYY') || ' a ' || to_char(max(t.data_mov), 'MM/YYYY') AS periodo,
       string_agg(DISTINCT t.tipo, ', ') AS formas,
       c.nome AS sugestao, u.confianca, u.motivo, u.status, ca.nome AS atual
FROM ult u
JOIN contrapartes cp ON cp.id = u.contraparte_id
LEFT JOIN categorias c ON c.id = u.categoria_id
LEFT JOIN categorias ca ON ca.id = cp.categoria_id
JOIN v_movimentos t ON t.contraparte_id = cp.id AND t.valor < 0
GROUP BY cp.id, c.nome, u.confianca, u.motivo, u.status, ca.nome
ORDER BY total DESC
"""

COLUNAS = [("ID", 7), ("Recebedor", 32), ("Tipo doc.", 10), ("CPF/CNPJ", 17), ("Pagamentos", 11),
           ("Total pago (R$)", 16), ("Período", 18), ("Formas", 18), ("Sugestão do LLM", 28),
           ("Confiança", 10), ("Motivo", 50), ("Aceitar? (S)", 10), ("Categoria final", 30), ("Observação", 30),
           ("% acumulado do valor", 12)]


def exportar() -> Path:
    with conectar() as con:
        linhas = con.execute(SQL).fetchall()
        cats = [r[0] for r in con.execute("SELECT nome FROM categorias ORDER BY grupo, nome")]
    wb = Workbook()
    ws = wb.active
    ws.title = "Revisão"
    ws.append([c for c, _ in COLUNAS])
    soma_total = float(sum(r[5] for r in linhas)) or 1.0
    acumulado = 0.0
    for r in linhas:
        id_, rec, tdoc, doc, n, total, per, formas, sug, conf, motivo, status, atual = r
        acumulado += float(total)
        ws.append([id_, rec, tdoc, doc, n, float(total), per, formas, sug or "Indeterminado",
                   float(conf or 0), motivo, None, atual, None, acumulado / soma_total])

    cab = PatternFill("solid", fgColor="1F3A5F")
    for i, (_, larg) in enumerate(COLUNAS, 1):
        cel = ws.cell(row=1, column=i)
        cel.font, cel.fill = Font(bold=True, color="FFFFFF"), cab
        cel.alignment = Alignment(vertical="center", wrap_text=True)
        ws.column_dimensions[get_column_letter(i)].width = larg
    ws.row_dimensions[1].height = 30
    ws.freeze_panes = "C2"
    ws.auto_filter.ref = ws.dimensions
    n = ws.max_row
    for row in ws.iter_rows(min_row=2, max_row=n):
        row[5].number_format = "#,##0.00"
        row[9].number_format = "0%"
        row[14].number_format = "0%"
        row[11].fill = PatternFill("solid", fgColor="FFF4CC")   # colunas para decidir
        row[12].fill = PatternFill("solid", fgColor="FFF4CC")
    ws.conditional_formatting.add(f"J2:J{n}", CellIsRule(operator="lessThan", formula=["0.5"],
                                                         font=Font(color="B00020")))

    lista = wb.create_sheet("Categorias")
    for c in cats:
        lista.append([c])
    lista.column_dimensions["A"].width = 36
    dv = DataValidation(type="list", formula1=f"=Categorias!$A$1:$A${len(cats)}", allow_blank=True,
                        error="Escolha uma categoria da lista (aba Categorias).", showErrorMessage=True)
    ws.add_data_validation(dv)
    dv.add(f"M2:M{max(n, 2)}")
    sn = DataValidation(type="list", formula1='"S,N"', allow_blank=True)
    ws.add_data_validation(sn)
    sn.add(f"L2:L{max(n, 2)}")

    info = wb.create_sheet("Como usar")
    for linha in [
        ["Revisão de categorias — Auditoria PCSF"],
        [f"Gerado em {datetime.now():%d/%m/%Y %H:%M}. {n - 1} recebedores."],
        [""],
        ["1. Os recebedores estão do maior para o menor valor pago. A última coluna mostra o % acumulado:"],
        ["   revisar só as primeiras linhas já cobre a maior parte do dinheiro."],
        ["2. Sugestão certa: digite S em 'Aceitar?'. Sugestão errada: escolha a categoria em 'Categoria final'."],
        ["3. Deixe em branco o que não quiser decidir agora. Nada vem pré-preenchido: o LLM erra com confiança alta."],
        ["4. Salve o arquivo e rode: python -m pcsf.revisao importar"],
        ["A categoria escolhida vale para todos os pagamentos daquele recebedor, inclusive meses futuros."],
    ]:
        info.append(linha)
    info.column_dimensions["A"].width = 100
    info["A1"].font = Font(bold=True, size=14)

    ARQ.parent.mkdir(exist_ok=True)
    wb.save(ARQ)
    return ARQ


def importar(arq: Path = ARQ) -> None:
    ws = load_workbook(arq, read_only=True)["Revisão"]
    with conectar() as con:
        cats = {nome: id_ for id_, nome in con.execute("SELECT id, nome FROM categorias")}
        aceitas = corrigidas = ignoradas = 0
        for row in ws.iter_rows(min_row=2, values_only=True):
            id_, sugestao, aceitar, final = row[0], row[8], row[11], row[12]
            if not final and str(aceitar or "").strip().upper() == "S" and sugestao != "Indeterminado":
                final = sugestao
            if not id_ or not final:
                ignoradas += 1
                continue
            if final not in cats:
                print(f"  ! categoria desconhecida '{final}' (recebedor {id_}); ignorado")
                continue
            aceita = final == sugestao
            con.execute("UPDATE contrapartes SET categoria_id = %s WHERE id = %s", (cats[final], id_))
            con.execute("""UPDATE transacoes SET categoria_id = %s, categoria_origem = %s
                           WHERE contraparte_id = %s AND valor < 0""", (cats[final], "llm" if aceita else "manual", id_))
            con.execute("""UPDATE sugestoes_categoria SET status = %s, revisado_em = now()
                           WHERE id = (SELECT max(id) FROM sugestoes_categoria WHERE contraparte_id = %s)""",
                        ("aceita" if aceita else "corrigida", id_))
            aceitas += aceita
            corrigidas += not aceita
        con.commit()
    print(f"importado: {aceitas} sugestões aceitas, {corrigidas} corrigidas, {ignoradas} sem decisão")


def main():
    ap = argparse.ArgumentParser(description="Revisão de categorias em Excel")
    ap.add_argument("acao", choices=["exportar", "importar"])
    ap.add_argument("--arquivo", type=Path, default=ARQ)
    a = ap.parse_args()
    if a.acao == "exportar":
        print(f"planilha gerada: {exportar()}")
    else:
        importar(a.arquivo)


if __name__ == "__main__":
    main()

"""Relatórios em Excel para uso em planilhas.

Uso:
    python -m pcsf.relatorios balancete     # saidas/balancete_selecionado.xlsx (contas da lista)
    python -m pcsf.relatorios movimentos    # saidas/movimentos_financeiros.xlsx (8 strings dos extratos)
    python -m pcsf.relatorios todos
    --cpf-completo   mostra CPF sem máscara (por padrão, mascarado: ***.456.789-**)
"""
from __future__ import annotations

import argparse
import re
from collections import defaultdict
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from .db import conectar

SAIDAS = Path(__file__).resolve().parent.parent / "saidas"
CPF = re.compile(r"(?<!\d)(\d{3})(\d{3})(\d{3})(\d{2})(?!\d)")
AZUL = PatternFill("solid", fgColor="1F3A5F")


def mascara(v, completo: bool):
    if completo or not isinstance(v, str):
        return v
    return CPF.sub(lambda m: f"***.{m.group(2)}.{m.group(3)}-**", v)


def _aba(wb, titulo, colunas, linhas, moeda=(), primeira=False):
    ws = wb.active if primeira else wb.create_sheet()
    ws.title = titulo
    ws.append(colunas)
    for l in linhas:
        ws.append([float(v) if isinstance(v, Decimal) else v for v in l])
    for i, c in enumerate(colunas, 1):
        cel = ws.cell(row=1, column=i)
        cel.font, cel.fill = Font(bold=True, color="FFFFFF"), AZUL
        cel.alignment = Alignment(wrap_text=True, vertical="center")
        larg = max([len(str(c))] + [len(str(l[i - 1] or "")) for l in linhas[:300]]) + 2
        ws.column_dimensions[get_column_letter(i)].width = min(max(larg, 9), 55)
        if c in moeda or (isinstance(c, str) and re.match(r"^\d{2}/\d{4}$", c)) or c == "Total":
            for row in ws.iter_rows(min_row=2, min_col=i, max_col=i):
                row[0].number_format = "#,##0.00"
    ws.freeze_panes = "B2" if primeira is False else "A2"
    ws.auto_filter.ref = ws.dimensions
    return ws


def _pivo(linhas, chave, mes, valor):
    """Tabela string × mês (soma), com coluna Total."""
    meses = sorted({l[mes] for l in linhas}, key=lambda m: (m[3:], m[:2]))
    tab, ordem = defaultdict(lambda: defaultdict(Decimal)), []
    for l in linhas:
        if l[chave] not in tab:
            ordem.append(l[chave])
        tab[l[chave]][l[mes]] += l[valor] or Decimal(0)
    cols = ["String"] + meses + ["Total"]
    rows = [[k] + [tab[k].get(m) for m in meses] + [sum(tab[k].values())] for k in ordem]
    return cols, rows


def _fonte(wb, texto: list[str]):
    ws = wb.create_sheet("Fonte")
    for t in [f"Gerado em {datetime.now():%d/%m/%Y %H:%M}"] + texto:
        ws.append([t])
    ws.column_dimensions["A"].width = 130


def balancete(ini: str | None = None, fim: str | None = None) -> Path:
    """ini/fim no formato AAAA-MM (opcionais): limita o relatório a esse intervalo de meses."""
    p = {"ini": f"{ini}-01" if ini else None, "fim": f"{fim}-01" if fim else None}
    periodo = "(%(ini)s::date IS NULL OR {c} >= %(ini)s::date) AND (%(fim)s::date IS NULL OR {c} <= %(fim)s::date)"
    with conectar() as con:
        rows = con.execute("""
            SELECT relatorio, mes_ano, string, debito, credito, natureza, codigo, tipo, grupo,
                   saldo_anterior, saldo_anterior_nat, saldo_atual, saldo_atual_nat, pagina
            FROM v_balancete_selecionado WHERE """ + periodo.format(c="competencia") + """
            ORDER BY natureza DESC, competencia, ordem""", p).fetchall()
        faltam = con.execute("""
            SELECT f.codigo, f.descricao, f.natureza, string_agg(to_char(d.competencia, 'MM/YYYY'), ', ' ORDER BY d.competencia)
            FROM balancete_filtros f CROSS JOIN documentos d
            WHERE f.ativo AND """ + periodo.format(c="d.competencia") + """
              AND NOT EXISTS (SELECT 1 FROM balancete b WHERE b.codigo = f.codigo AND b.documento_id = d.id)
            GROUP BY 1, 2, 3, f.ordem ORDER BY f.ordem""", p).fetchall()
    wb = Workbook()
    cols = ["Relatório", "Mês/ano", "String", "Débito", "Crédito", "Natureza", "Código", "Tipo", "Grupo",
            "Saldo anterior", "Nat.", "Saldo atual", "Nat.", "Página"]
    _aba(wb, "Linhas", cols, rows, moeda=("Débito", "Crédito", "Saldo anterior", "Saldo atual"), primeira=True)
    # receitas: o valor do mês é o crédito; despesas: o débito. Chave com código (nomes se repetem).
    for nome, natureza, idx in (("Receitas por mês (crédito)", "receita", 4), ("Despesas por mês (débito)", "despesa", 3)):
        sel = [list(r) for r in rows if r[5] == natureza]
        for r in sel:
            r[2] = f"[{r[6]}] {r[2]}"
        c, r = _pivo(sel, 2, 1, idx)
        _aba(wb, nome, c, r)
    _aba(wb, "Sem movimento", ["Código", "Conta", "Natureza", "Meses em que não aparece no balancete"], faltam)
    texto_periodo = (f"Período: {ini[5:]}/{ini[:4] if ini else ''} a {fim[5:]}/{fim[:4]}" if ini and fim
                     else f"Período: a partir de {ini[5:]}/{ini[:4]}" if ini
                     else f"Período: até {fim[5:]}/{fim[:4]}" if fim else "Período: todos os meses carregados")
    _fonte(wb, [texto_periodo,
                "Origem: Balancete Analítico de cada mês (páginas indicadas), contas da lista balancete_filtros.",
                "Conferências feitas em todos os meses: débitos = créditos (partidas dobradas), totais de grupo = soma das "
                "contas, saldo anterior + débito - crédito = saldo atual. Nenhuma divergência.",
                "Tipo 'grupo': valor da linha de total do grupo (=Grupo). Tipo 'conta': conta analítica.",
                "Receitas: o crédito é a receita do mês (débito costuma ser estorno). Despesas: o débito é o gasto do "
                "mês (crédito costuma ser estorno/reclassificação).",
                "Nomes se repetem entre receita e despesa (ex.: Krav Maga [41532] receita e [41546] despesa): "
                "nas abas por mês a conta aparece com o código.",
                "Meses ausentes = conta sem movimento no mês (não aparece no PDF)."])
    sufixo = f"_{ini or 'inicio'}_a_{fim or 'fim'}" if (ini or fim) else ""
    arq = SAIDAS / f"balancete_selecionado{sufixo}.xlsx"
    SAIDAS.mkdir(exist_ok=True)
    wb.save(arq)
    return arq


def movimentos(cpf_completo=False) -> Path:
    with conectar() as con:
        rows = con.execute("""
            SELECT relatorio, pagina, mes_ano, to_char(data_mov, 'DD/MM/YYYY'), string, valor, favorecido, papel,
                   variante, CASE WHEN interno THEN 'sim' ELSE '' END, historico, conta, origem
            FROM movimentos_financeiros ORDER BY competencia, data_mov, id""").fetchall()
    rows = [[mascara(v, cpf_completo) for v in r] for r in rows]
    wb = Workbook()
    cols = ["Relatório", "Página", "Mês/ano", "Data", "String", "Valor", "Favorecido", "Papel",
            "Variante do banco", "Interno", "Histórico original", "Conta", "Leitura"]
    _aba(wb, "Movimentos", cols, rows, moeda=("Valor",), primeira=True)
    c, r = _pivo(rows, 4, 2, 5)
    _aba(wb, "Resumo por mês", c, r)
    _fonte(wb, ["Origem: extratos bancários anexos aos balancetes (Santander), conferidos com os saldos do banco.",
                "Strings: Pix recebido, Saque dinheiro, Pagamento fornecedor, Cheque emitido, TED enviado, Pix enviado, "
                "Dep cheque, TAR. 'Variante do banco' mostra a forma exata do histórico quando difere da principal.",
                "Pix recebido: o CPF/CNPJ é de quem PAGOU (papel = pagador). Saque, cheque, TAR e pagamento a "
                "fornecedor em lote (PAGFOR) não trazem favorecido no extrato.",
                "Interno = transferência entre contas do próprio clube (inclui as contas do Sicredi registradas no "
                "balancete): não é receita nem despesa.",
                "Linhas repetidas entre impressões do extrato foram removidas. Valor: entrada > 0, saída < 0.",
                "CPF " + ("completo." if cpf_completo else "mascarado (LGPD). Use --cpf-completo para ver inteiro.")])
    arq = SAIDAS / "movimentos_financeiros.xlsx"
    SAIDAS.mkdir(exist_ok=True)
    wb.save(arq)
    return arq


def main():
    ap = argparse.ArgumentParser(description="Relatórios Excel")
    ap.add_argument("qual", choices=["balancete", "movimentos", "todos"])
    ap.add_argument("--cpf-completo", action="store_true")
    a = ap.parse_args()
    if a.qual in ("balancete", "todos"):
        print("gerado:", balancete())
    if a.qual in ("movimentos", "todos"):
        print("gerado:", movimentos(a.cpf_completo))


if __name__ == "__main__":
    main()

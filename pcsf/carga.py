"""Carga dos balancetes no banco.

Uso:
    python -m pcsf.carga "balancetes pcsf"            # carrega os PDFs novos da pasta
    python -m pcsf.carga "balancetes pcsf" --recarregar   # apaga e recarrega tudo

Etapas por arquivo: hash (evita duplicar) -> extração (texto ou OCR) -> conferência com o banco
-> classificação -> gravação. No fim: deduplicação entre extratos e categorização por regras.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

import pymupdf

from .balancete import gravar as gravar_balancete
from .classificar import Vocabulario, compacto, contraparte, interna, sem_acento, tipo_de
from .conciliacao import resumo_mensal, saldo_corrido
from .db import conectar
from .extratos import extrair
from .ocr import pagina_ocr

MESES = {"JAN": 1, "FEV": 2, "MAR": 3, "ABR": 4, "MAI": 5, "JUN": 6,
         "JUL": 7, "AGO": 8, "SET": 9, "OUT": 10, "NOV": 11, "DEZ": 12}


def competencia(arquivo: str) -> date:
    m = re.search(r"(20\d{2})-(\d{2})", arquivo)
    if m:
        return date(int(m.group(1)), int(m.group(2)), 1)
    m = re.search(r"(" + "|".join(MESES) + r")\w*[-_ ]*(20\d{2})", arquivo.upper())
    if m:
        return date(int(m.group(2)), MESES[m.group(1)], 1)
    raise ValueError(f"não sei o mês/ano de '{arquivo}' (use o padrão 'Balancete AAAA-MM-MES.pdf')")


def sha256(caminho: Path) -> str:
    h = hashlib.sha256()
    with open(caminho, "rb") as f:
        for bloco in iter(lambda: f.read(1 << 20), b""):
            h.update(bloco)
    return h.hexdigest()


def log(msg: str) -> None:
    print(msg, flush=True)


def carregar(pasta: Path, recarregar: bool = False) -> None:
    arquivos = sorted(pasta.glob("*.pdf"))
    if not arquivos:
        sys.exit(f"nenhum PDF em {pasta}")
    with conectar() as con:
        if recarregar:
            con.execute("TRUNCATE documentos, transacoes, conciliacoes, contrapartes, dre_lancamentos, balancete RESTART IDENTITY CASCADE")
        ja = {r[0] for r in con.execute("SELECT hash_sha256 FROM documentos")}

        # 1) extração de todos os arquivos (o vocabulário do OCR depende dos meses com texto)
        extraidos = []
        for arq in arquivos:
            h = sha256(arq)
            if h in ja:
                log(f"  = {arq.name}: já carregado")
                continue
            log(f"  > {arq.name}: extraindo...")
            ex = extrair(str(arq), ocr=pagina_ocr)
            with pymupdf.open(arq) as pdf:
                npag = pdf.page_count
            extraidos.append((arq, h, npag, ex))

        if not extraidos:
            log("nada novo para carregar.")
            return

        textos = [l.descricao for _, _, _, ex in extraidos for l in ex.lancamentos
                  if l.valor is not None and not l.formato.endswith("ocr")]
        textos += [r[0] for r in con.execute("SELECT descricao FROM transacoes WHERE origem = 'texto' LIMIT 50000")]
        vocab = Vocabulario(textos)

        # 2) gravação
        for arq, h, npag, ex in extraidos:
            comp = competencia(arq.name)
            trechos = saldo_corrido(ex)
            resumos = resumo_mensal(ex)
            ok = all(t.ok for t in trechos) and all(r["ok"] for r in resumos)
            movs = [l for l in ex.lancamentos if l.valor is not None and l.data is not None]
            doc_id = con.execute(
                """INSERT INTO documentos (arquivo, hash_sha256, competencia, paginas, paginas_extrato, paginas_ocr,
                                           lancamentos, conciliado, status)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
                (arq.name, h, comp, npag, ex.paginas_extrato, ex.paginas_escaneadas, len(movs), ok,
                 "carregado" if ok else "revisar"),
            ).fetchone()[0]

            por_conta = defaultdict(list)
            for t in trechos:
                por_conta[t.conta].append(t)
            for conta, ts in por_conta.items():
                falhas = [{"pagina": t.pagina, "data": str(t.data), "esperado": str(t.esperado), "banco": str(t.impresso)}
                          for t in ts if not t.ok]
                con.execute(
                    """INSERT INTO conciliacoes (documento_id, conta, tipo, trechos_ok, trechos_total, ok, detalhe)
                       VALUES (%s, %s, 'saldo_corrido', %s, %s, %s, %s)""",
                    (doc_id, conta, sum(t.ok for t in ts), len(ts), not falhas, json.dumps(falhas) if falhas else None),
                )
            for r in resumos:
                con.execute(
                    """INSERT INTO conciliacoes (documento_id, conta, tipo, creditos_extraidos, creditos_banco,
                                                debitos_extraidos, debitos_banco, ok)
                       VALUES (%s, %s, 'resumo_mensal', %s, %s, %s, %s, %s)""",
                    (doc_id, r["conta"], r["creditos_extraidos"], r["creditos_banco"],
                     r["debitos_extraidos"], r["debitos_banco"], r["ok"]),
                )

            for seq, l in enumerate(movs, 1):
                ocr = l.formato.endswith("ocr")
                desc = vocab.restaurar(l.descricao) if ocr else l.descricao
                tipo = tipo_de(desc)
                cp = contraparte(desc, tipo)
                con.execute("INSERT INTO contas_bancarias (conta) VALUES (%s) ON CONFLICT DO NOTHING", (l.conta,))
                cp_id = None
                chave = cp.doc if cp.doc and cp.tipo_doc != "CNPJ_RAIZ" else (
                    cp.doc if cp.tipo_doc == "CNPJ_RAIZ" else (compacto(cp.nome) if cp.nome else None))
                if chave:
                    cp_id = con.execute(
                        """INSERT INTO contrapartes (chave, tipo, documento, nome_extrato)
                           VALUES (%s, %s, %s, %s)
                           ON CONFLICT (chave) DO UPDATE SET nome_extrato = COALESCE(contrapartes.nome_extrato, EXCLUDED.nome_extrato)
                           RETURNING id""",
                        (chave, cp.tipo_doc or "NOME", cp.doc, cp.nome),
                    ).fetchone()[0]
                hash_linha = hashlib.sha1(
                    f"{l.conta}|{l.data}|{compacto(desc)}|{l.valor}".encode()).hexdigest()
                con.execute(
                    """INSERT INTO transacoes (documento_id, seq, bloco, pagina, linha_y, competencia, data_mov, conta, tipo,
                                               direcao, valor, interna, contraparte_id, contraparte_doc,
                                               contraparte_nome, descricao, documento_banco, saldo_apos, origem, hash_linha)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (doc_id, seq, l.bloco, l.pagina, l.linha_y, comp, l.data, l.conta, tipo,
                     "E" if l.valor > 0 else "S", l.valor, interna(desc, tipo), cp_id, cp.doc, cp.nome,
                     desc, l.documento, l.saldo, "ocr" if ocr else "texto", hash_linha),
                )
            cb = gravar_balancete(con, doc_id, comp, str(arq))
            log(f"  + {arq.name}: balancete {cb['linhas']} linhas, partidas dobradas "
                f"{'OK' if cb['partidas_dobradas'] and not cb['falhas'] else 'COM DIVERGÊNCIAS'}")
            log(f"  + {arq.name}: {len(movs)} lançamentos, conferência {'OK' if ok else 'COM DIVERGÊNCIAS'}"
                + (f", {len(ex.paginas_escaneadas)} páginas por OCR" if ex.paginas_escaneadas else ""))

        deduplicar(con)
        categorizar(con)
        con.commit()
        resumo(con)


def deduplicar(con) -> None:
    """A mesma linha pode aparecer em duas impressões do extrato (ex.: dia 16/06 nas duas quinzenas,
    ou 01/09 no fim do extrato de agosto). Lançamentos idênticos legítimos (dois PIX iguais no mesmo dia)
    aparecem repetidos dentro da MESMA impressão, então a regra é: para cada linha (hash), vale o maior
    número de ocorrências numa única impressão; as cópias de outras impressões viram duplicatas."""
    con.execute("UPDATE transacoes SET duplicada_de = NULL")
    linhas = con.execute(
        """SELECT id, hash_linha, documento_id, bloco, competencia, data_mov
           FROM transacoes ORDER BY hash_linha, documento_id, seq"""
    ).fetchall()
    grupos = defaultdict(lambda: defaultdict(list))
    for id_, h, doc, bloco, comp, data_mov in linhas:
        # prefere a cópia do arquivo do próprio mês do lançamento
        mesmo_mes = (comp.year, comp.month) == (data_mov.year, data_mov.month)
        grupos[h][(not mesmo_mes, doc, bloco)].append(id_)
    dups = 0
    for h, por_bloco in grupos.items():
        if len(por_bloco) < 2:
            continue
        ordem = sorted(por_bloco)                       # bloco preferido primeiro
        principal = max(ordem, key=lambda k: len(por_bloco[k]))   # empate: o primeiro (preferido)
        canon = por_bloco[principal]
        for k in ordem:
            if k == principal:
                continue
            for i, id_ in enumerate(por_bloco[k]):
                con.execute("UPDATE transacoes SET duplicada_de = %s WHERE id = %s", (canon[min(i, len(canon) - 1)], id_))
                dups += 1
    con.execute("""UPDATE documentos d SET duplicados = x.n
                   FROM (SELECT documento_id, count(*) n FROM transacoes WHERE duplicada_de IS NOT NULL GROUP BY 1) x
                   WHERE x.documento_id = d.id""")
    log(f"  deduplicação: {dups} cópias marcadas")


def categorizar(con) -> None:
    """Categoria de cada lançamento, nesta ordem de precedência:
    1. decisão revisada para o recebedor (contrapartes.categoria_id, vinda da revisão em Excel);
    2. regra por palavra-chave (regras_categoria);
    3. tipo do lançamento (tarifa, folha, tributo, conta de consumo, PIX recebido de sócio).
    Lançamentos marcados à mão um a um (categoria_origem = 'manual' sem recebedor) não são tocados."""
    regras = con.execute(
        "SELECT padrao, categoria_id FROM regras_categoria WHERE ativo ORDER BY prioridade, id").fetchall()
    compiladas = [(re.compile(p), c) for p, c in regras]
    cat = {n: i for i, n in con.execute("SELECT id, nome FROM categorias")}
    por_tipo = {"TARIFA": cat["Tarifas bancárias"], "FOLHA": cat["Pessoal"], "TRIBUTO": cat["Tributos"],
                "CONTA_CONSUMO": cat["Utilidades"], "PIX_RECEBIDO": cat["Mensalidades e associados"],
                "COBRANCA_RECEBIDA": cat["Mensalidades e associados"]}
    linhas = con.execute(
        """SELECT t.id, t.descricao, COALESCE(t.contraparte_nome, ''), t.tipo, t.valor, cp.categoria_id
           FROM transacoes t LEFT JOIN contrapartes cp ON cp.id = t.contraparte_id
           WHERE NOT t.interna AND NOT (COALESCE(t.categoria_origem, '') = 'manual' AND cp.categoria_id IS NULL)""").fetchall()
    cont = {"revisada": 0, "regra": 0, "tipo": 0}
    with con.cursor() as cur:
        for id_, desc, nome, tipo, valor, cat_revisada in linhas:
            origem, c = None, None
            if cat_revisada and valor < 0:
                c, origem = cat_revisada, "manual"
                cont["revisada"] += 1
            else:
                alvo = sem_acento(f"{nome} {desc}").upper()
                c = next((ci for rx, ci in compiladas if rx.search(alvo)), None)
                if c:
                    origem = "regra"
                    cont["regra"] += 1
                elif tipo in por_tipo:
                    c, origem = por_tipo[tipo], "regra"
                    cont["tipo"] += 1
            cur.execute("UPDATE transacoes SET categoria_id = %s, categoria_origem = %s WHERE id = %s", (c, origem, id_))
    log(f"  categorização: {cont['revisada']} pela revisão, {cont['regra']} por palavra-chave, "
        f"{cont['tipo']} pelo tipo, de {len(linhas)} lançamentos")


def resumo(con) -> None:
    log("\nResumo por mês (sem duplicatas e sem movimentos internos):")
    for mes, ent, sai, res, n in con.execute("SELECT * FROM v_resumo_mensal"):
        log(f"  {mes:%Y-%m}  entradas {ent or 0:>14,.2f}  saídas {sai or 0:>14,.2f}  resultado {res or 0:>14,.2f}  ({n} lanç.)")


def main() -> None:
    ap = argparse.ArgumentParser(description="Carga dos balancetes do PCSF")
    ap.add_argument("pasta", type=Path)
    ap.add_argument("--recarregar", action="store_true", help="apaga os dados e recarrega todos os PDFs")
    a = ap.parse_args()
    carregar(a.pasta, a.recarregar)


if __name__ == "__main__":
    main()

"""Sugestão de categoria por recebedor, usando o LLM local. Nada é aplicado sem revisão.

Uso:
    python -m pcsf.sugerir                 # sugere para os recebedores sem categoria e sem sugestão
    python -m pcsf.sugerir --limite 20     # só os 20 maiores (teste)
    python -m pcsf.sugerir --modelo qwen2.5:7b --url http://127.0.0.1:11434
"""
from __future__ import annotations

import argparse
import json

from .db import conectar
from .llm import chat_json, config

SYSTEM = """Você classifica pagamentos feitos por um clube social e esportivo — com piscinas,
quadras, náutica, restaurante, salões de festa e eventos — a partir do nome do recebedor como aparece no
extrato bancário (cortado em 25 caracteres).

Regras:
- Escolha UMA categoria da lista, pelo nome exato.
- Use "Indeterminado" quando o nome não der pista suficiente (ex.: nome de pessoa física sem outra informação).
  Não invente: é melhor "Indeterminado" do que um palpite.
- confianca: 0 a 1. Pessoa física sem pista: no máximo 0.3.
- motivo: frase curta em português explicando a pista usada.

Dicas do contexto:
- Ticket, Alelo, VR, Sodexo, Sul América, Unimed, Amil, Bradesco Saúde: benefícios/plano de saúde -> "Seguros e saúde".
- CEF / Caixa Econômica recebendo PIX: em geral FGTS, guias ou consignado -> "Pessoal" (confiança média).
- Congelados, frios, hortifruti, açougue, padaria, atacadista de alimentos -> "Restaurante e alimentação".
- Combustível, posto, transportadora, fretes -> "Transporte".
- Velas, náutica, barcos, escola de ginástica/natação/tênis -> "Atividades esportivas e escolinhas".
- Incineração, coleta de lixo, dedetização, limpeza -> "Manutenção e obras".
- Contas bancárias (ex.: "748-0000-0000...") ou bancos como recebedor de TED: "Indeterminado".
- Distribuidora de bebidas/cerveja/chopp -> "Bebidas". Buffet/salgados/doces -> "Buffet".
Responda só JSON: {"itens": [{"id": <id>, "categoria": "<nome>", "confianca": <0-1>, "motivo": "<texto>"}]}"""


def categorias(con) -> dict[str, tuple[int, str]]:
    rows = con.execute("SELECT id, nome, descricao FROM categorias WHERE grupo <> 'Receitas' ORDER BY grupo, nome")
    return {nome: (id_, desc) for id_, nome, desc in rows}


def pendentes(con, limite: int | None):
    sql = """
        SELECT cp.id, cp.nome_extrato, cp.tipo, cp.documento,
               count(*) AS n, round(-sum(t.valor), 2) AS total,
               min(t.data_mov) AS primeiro, max(t.data_mov) AS ultimo,
               array_agg(DISTINCT t.tipo) AS tipos,
               (array_agg(t.descricao ORDER BY t.valor))[1] AS exemplo
        FROM v_movimentos t JOIN contrapartes cp ON cp.id = t.contraparte_id
        WHERE t.valor < 0 AND t.categoria_id IS NULL
          AND NOT EXISTS (SELECT 1 FROM sugestoes_categoria s WHERE s.contraparte_id = cp.id)
        GROUP BY cp.id ORDER BY total DESC"""
    return con.execute(sql + (f" LIMIT {int(limite)}" if limite else "")).fetchall()


def prompt(lote, cats) -> str:
    lista = "\n".join(f"- {n}: {d}" for n, (_, d) in cats.items()) + "\n- Indeterminado: sem pista suficiente"
    itens = [{
        "id": r[0], "recebedor": r[1] or "(sem nome)", "tipo_doc": r[2], "pagamentos": r[4],
        "total_reais": float(r[5]), "periodo": f"{r[6]:%m/%Y} a {r[7]:%m/%Y}", "formas": r[8], "historico": r[9][:90],
    } for r in lote]
    return f"Categorias:\n{lista}\n\nRecebedores:\n{json.dumps(itens, ensure_ascii=False, indent=1)}"


def sugerir(limite=None, lote_tam=12, url=None, modelo=None, gravar=True, verbose=True):
    u, m = config()
    url, modelo = url or u, modelo or m
    with conectar() as con:
        cats = categorias(con)
        rows = pendentes(con, limite)
        resultados, tempo = [], 0.0
        for i in range(0, len(rows), lote_tam):
            lote = rows[i:i + lote_tam]
            resp, s = chat_json(SYSTEM, prompt(lote, cats), url=url, modelo=modelo)
            tempo += s
            por_id = {int(x.get("id", -1)): x for x in resp.get("itens", []) if str(x.get("id", "")).lstrip("-").isdigit()}
            for r in lote:
                x = por_id.get(r[0], {})
                nome_cat = (x.get("categoria") or "Indeterminado").strip()
                cat_id = cats.get(nome_cat, (None, None))[0]
                conf = float(x.get("confianca") or 0)
                motivo = x.get("motivo") or ("categoria fora da lista: " + nome_cat if nome_cat not in cats else "")
                resultados.append((r, nome_cat if cat_id else "Indeterminado", conf, motivo))
                if gravar:
                    con.execute(
                        """INSERT INTO sugestoes_categoria (contraparte_id, categoria_id, confianca, motivo, modelo)
                           VALUES (%s, %s, %s, %s, %s)""", (r[0], cat_id, conf, motivo, modelo))
            if gravar:
                con.commit()
            if verbose:
                print(f"  {min(i + lote_tam, len(rows))}/{len(rows)} recebedores ({tempo:.0f}s)", flush=True)
    return resultados, tempo


def main():
    ap = argparse.ArgumentParser(description="Sugere categorias com o LLM local (revisão obrigatória depois)")
    ap.add_argument("--limite", type=int)
    ap.add_argument("--lote", type=int, default=12)
    ap.add_argument("--url")
    ap.add_argument("--modelo")
    a = ap.parse_args()
    res, t = sugerir(a.limite, a.lote, a.url, a.modelo)
    print(f"{len(res)} sugestões em {t:.0f}s. Revise com: python -m pcsf.revisao exportar")


if __name__ == "__main__":
    main()

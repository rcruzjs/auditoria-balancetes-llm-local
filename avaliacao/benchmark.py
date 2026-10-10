"""Benchmark do chat NL→SQL: compara LLMs locais nas mesmas perguntas, com respostas de referência.

Cada pergunta de avaliacao/perguntas.json tem um SQL de referência escrito à mão. O benchmark pede o SQL
ao modelo pelo mesmo caminho do chat (web.app.gerar_sql: prompt, trava de segurança, usuário somente leitura
e uma correção automática), executa e compara o resultado com o da referência.

Uso:
    .venv/Scripts/python -m avaliacao.benchmark --validar                  # só confere as referências
    .venv/Scripts/python -m avaliacao.benchmark chat-8b chat-moe-30b ollama/qwen2.5:7b
    .venv/Scripts/python -m avaliacao.benchmark chat-8b --repeticoes 3 --so mov-01 bal-05

Modelos: nome no llama-swap (LLM_URL do .env) ou "ollama/<modelo>" para o Ollama em :11434.
Saída: detalhe em saidas/benchmark_<data>.json (tem valores reais: fica fora do Git) e
resumo, sem valores, em avaliacao/RESULTADOS.md.
"""
from __future__ import annotations

import argparse
import json
import time
import urllib.request
from collections import Counter
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from fastapi import HTTPException

from pcsf.llm import chat_json, config
from web.app import consulta, gerar_sql

RAIZ = Path(__file__).resolve().parent.parent
PERGUNTAS = Path(__file__).with_name("perguntas.json")
# Nomes fictícios usados em perguntas.json -> nomes reais do plano de contas (arquivo local, fora do Git)
APELIDOS = Path(__file__).with_name("apelidos.json")
OLLAMA = "http://127.0.0.1:11434"


# ----------------------------------------------------------------------------- comparação
def numeros(linhas) -> Counter:
    """Valores numéricos do resultado, sem sinal e com 2 casas (gasto pode vir positivo ou negativo)."""
    c: Counter = Counter()
    for linha in linhas:
        for v in linha:
            if isinstance(v, bool) or v is None:
                continue
            if isinstance(v, (int, float, Decimal)):
                c[round(abs(float(v)), 2)] += 1
    return c


def textos(linhas) -> Counter:
    c: Counter = Counter()
    for linha in linhas:
        for v in linha:
            if isinstance(v, (date, datetime)):
                c[v.isoformat()[:10]] += 1
            elif isinstance(v, str):
                c[v.strip().upper()] += 1
    return c


def confere(referencia: list, modelo: list) -> bool:
    """O resultado do modelo está certo se contém todos os números da referência (tolerante a nomes e ordem de
    colunas, a colunas extras e ao sinal) e não tem linhas demais (evita "acertar" despejando a tabela inteira).
    Nomes de conta/recebedor e datas da referência também precisam aparecer."""
    if not referencia:
        return not modelo
    if len(modelo) > 3 * len(referencia) + 2:
        return False
    ref_num, mod_num = numeros(referencia), numeros(modelo)
    if any(mod_num[k] < n for k, n in ref_num.items()):
        return False
    mod_txt = textos(modelo)
    ref_txt = {k: n for k, n in textos(referencia).items() if not k[:4].isdigit()}   # meses ('2025-01') podem vir em outro formato
    return all(mod_txt[k] >= n for k, n in ref_txt.items())


# ----------------------------------------------------------------------------- execução
def com_apelidos(pergunta: dict, apelidos: dict[str, str]) -> dict:
    """Troca os nomes fictícios da pergunta e do SQL de referência pelos nomes reais do banco."""
    p = dict(pergunta)
    for ficticio, real in apelidos.items():
        p["pergunta"] = p["pergunta"].replace(ficticio, real)
        p["sql"] = p["sql"].replace(ficticio, real)
    return p


def destino(nome: str) -> tuple[str, str]:
    if nome.startswith("ollama/"):
        return OLLAMA, nome.removeprefix("ollama/")
    return config()[0], nome


def descarregar_llama_swap() -> None:
    """Libera a GPU antes de usar o Ollama (os dois servidores disputam os 6 GB de VRAM)."""
    try:
        urllib.request.urlopen(f"{config()[0].rstrip('/')}/unload", timeout=30).read()
    except Exception:
        pass


def avaliar(pergunta: dict, url: str, modelo: str, ref_linhas: list) -> dict:
    r = {"id": pergunta["id"], "fonte": pergunta["fonte"], "conjunto": pergunta.get("conjunto", "ajuste")}
    t0 = time.perf_counter()
    try:
        g = gerar_sql(pergunta["pergunta"], url=url, modelo=modelo)
    except HTTPException:
        return r | {"status": "bloqueado", "segundos": time.perf_counter() - t0, "sql": None}
    except Exception as e:   # servidor fora do ar, JSON inválido etc.
        return r | {"status": "falha_llm", "detalhe": str(e)[:200], "segundos": time.perf_counter() - t0, "sql": None}
    r |= {"sql": g["sql"], "corrigido": g["corrigido"], "segundos": g["segundos"], "linhas": len(g["rows"])}
    if g["erro"]:
        return r | {"status": "erro_sql", "detalhe": g["erro"]}
    if not g["rows"] or all(v is None for l in g["rows"] for v in l):
        return r | {"status": "vazio"}
    return r | {"status": "certo" if confere(ref_linhas, g["rows"]) else "errado"}


def resumo(resultados: list[dict]) -> dict:
    n = len(resultados)
    st = Counter(r["status"] for r in resultados)
    tempos = sorted(r["segundos"] for r in resultados)
    return {"n": n, "certo": st["certo"], "acerto": st["certo"] / n if n else 0,
            "errado": st["errado"], "vazio": st["vazio"], "erro_sql": st["erro_sql"],
            "bloqueado": st["bloqueado"], "falha_llm": st["falha_llm"],
            "corrigidos": sum(1 for r in resultados if r.get("corrigido")),
            "tempo_medio": sum(tempos) / n if n else 0, "tempo_mediano": tempos[n // 2] if n else 0}


def acerto_por(res: list[dict], chave: str) -> dict[str, float]:
    total = Counter(r[chave] for r in res)
    return {k: sum(1 for r in res if r[chave] == k and r["status"] == "certo") / n for k, n in total.items()}


def tabela_md(resumos: dict[str, dict], por_fonte: dict[str, dict[str, float]], repeticoes: int,
              estabilidade: dict[str, float], por_conjunto: dict[str, dict[str, float]]) -> str:
    fontes = sorted({f for v in por_fonte.values() for f in v})
    l = [f"# Benchmark do chat NL→SQL\n",
         f"Gerado em {datetime.now():%d/%m/%Y %H:%M}. {next(iter(resumos.values()))['n'] // repeticoes} perguntas"
         f" × {repeticoes} repetição(ões). Detalhe (com valores reais) em `saidas/`, fora do Git.\n",
         "| Modelo | Acerto | Certo | Errado | Vazio | Erro SQL | Bloqueado | Falha LLM | Corrigidos | Tempo médio | Tempo mediano |",
         "|---|---|---|---|---|---|---|---|---|---|---|"]
    for m, s in resumos.items():
        l.append(f"| {m} | **{s['acerto']:.0%}** | {s['certo']} | {s['errado']} | {s['vazio']} | {s['erro_sql']} | "
                 f"{s['bloqueado']} | {s['falha_llm']} | {s['corrigidos']} | {s['tempo_medio']:.1f} s | {s['tempo_mediano']:.1f} s |")
    l += ["", "Acerto por fonte de dados:", "", "| Modelo | " + " | ".join(fontes) + " |", "|---" * (len(fontes) + 1) + "|"]
    for m, v in por_fonte.items():
        l.append(f"| {m} | " + " | ".join(f"{v.get(f, 0):.0%}" for f in fontes) + " |")
    conjuntos = sorted({c for v in por_conjunto.values() for c in v})
    l += ["", "Acerto por conjunto (*ajuste*: perguntas cujos erros orientaram o prompt; *validacao*: perguntas novas, "
          "não usadas para ajustar):", "", "| Modelo | " + " | ".join(conjuntos) + " |", "|---" * (len(conjuntos) + 1) + "|"]
    for m, v in por_conjunto.items():
        l.append(f"| {m} | " + " | ".join(f"{v.get(c, 0):.0%}" for c in conjuntos) + " |")
    if repeticoes > 1:
        l += ["", "Estabilidade (perguntas com o mesmo resultado em todas as repetições):", ""]
        l += [f"- {m}: {e:.0%}" for m, e in estabilidade.items()]
    l += ["", "Critério: o resultado do modelo precisa conter todos os números (e nomes) do resultado de referência, "
          "sem linhas demais. Status: *vazio* = SQL válido sem linhas; *erro SQL* = falhou mesmo após a correção "
          "automática; *bloqueado* = barrado pela trava de segurança; *corrigidos* = acertou o SQL na 2ª tentativa."]
    return "\n".join(l) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description="Benchmark do chat NL→SQL com LLMs locais")
    ap.add_argument("modelos", nargs="*", help='ex.: chat-8b chat-moe-30b "ollama/qwen2.5:7b"')
    ap.add_argument("--validar", action="store_true", help="só executa os SQL de referência")
    ap.add_argument("--repeticoes", type=int, default=1)
    ap.add_argument("--so", nargs="*", help="ids das perguntas (padrão: todas)")
    ap.add_argument("--saida", help="nome do resumo em avaliacao/ (padrão: RESULTADOS.md)", default="RESULTADOS.md")
    a = ap.parse_args()

    perguntas = json.loads(PERGUNTAS.read_text(encoding="utf-8"))
    apelidos = json.loads(APELIDOS.read_text(encoding="utf-8")) if APELIDOS.exists() else {}
    perguntas = [com_apelidos(p, apelidos) for p in perguntas]
    if a.so:
        perguntas = [p for p in perguntas if p["id"] in a.so]
    referencias = {}
    for p in perguntas:
        _, linhas = consulta(p["sql"], leitor=True)
        referencias[p["id"]] = linhas
        if a.validar:
            print(f"{p['id']}: {len(linhas)} linha(s)  {linhas[:2]}")
    if a.validar or not a.modelos:
        return

    # Ollama por último, para descarregar o llama-swap uma vez só
    modelos = sorted(a.modelos, key=lambda m: m.startswith("ollama/"))
    detalhe, resumos, por_fonte, por_conjunto, estabilidade = {}, {}, {}, {}, {}
    for nome in modelos:
        url, modelo = destino(nome)
        if url == OLLAMA:
            descarregar_llama_swap()
        print(f"\n== {nome}: aquecendo (carga do modelo, fora da medição)...", flush=True)
        try:
            chat_json("Responda só JSON.", 'Diga {"ok": true}', url=url, modelo=modelo, timeout=900)
        except Exception as e:
            print(f"   modelo indisponível: {e}")
            continue
        res = []
        for rep in range(a.repeticoes):
            for p in perguntas:
                r = avaliar(p, url, modelo, referencias[p["id"]]) | {"repeticao": rep + 1}
                res.append(r)
                print(f"   [{rep + 1}] {r['id']}: {r['status']:<10} {r['segundos']:6.1f} s"
                      + (" (corrigido)" if r.get("corrigido") else ""), flush=True)
        detalhe[nome], resumos[nome] = res, resumo(res)
        por_fonte[nome], por_conjunto[nome] = acerto_por(res, "fonte"), acerto_por(res, "conjunto")
        por_id: dict[str, set] = {}
        for r in res:
            por_id.setdefault(r["id"], set()).add(r["status"])
        estabilidade[nome] = sum(1 for s in por_id.values() if len(s) == 1) / len(por_id)
        s = resumos[nome]
        print(f"   => acerto {s['acerto']:.0%} ({s['certo']}/{s['n']}), tempo médio {s['tempo_medio']:.1f} s")

    if not resumos:
        return
    carimbo = f"{datetime.now():%Y-%m-%d_%H%M}"
    saidas = RAIZ / "saidas"
    saidas.mkdir(exist_ok=True)
    (saidas / f"benchmark_{carimbo}.json").write_text(
        json.dumps({"resumos": resumos, "detalhe": detalhe}, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    md = tabela_md(resumos, por_fonte, a.repeticoes, estabilidade, por_conjunto)
    (Path(__file__).with_name(a.saida)).write_text(md, encoding="utf-8")
    print("\n" + md)


if __name__ == "__main__":
    main()

"""Classificação determinística de cada lançamento: tipo, movimento interno e contraparte.

Nada aqui usa LLM: são regras sobre o histórico do banco, auditáveis e reproduzíveis.
"""
from __future__ import annotations

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass

from . import clube

CNPJ_CLUBE = clube.CNPJ

# (padrão sobre o histórico sem espaços e em maiúsculas, tipo) — a ordem importa
TIPOS = [
    (r"^PIXRECEBID[O0]", "PIX_RECEBIDO"),
    (r"^PIXENVIAD[O0]", "PIX_ENVIADO"),
    (r"^(DEVOLUCAO|DEVPIX|PIXDEVOLVID)", "PIX_DEVOLUCAO"),
    (r"^TEDRECEBIDA|^TEDCREDITO", "TED_RECEBIDA"),
    # pagamentos em lote pelo convênio PAGFOR: o extrato NÃO mostra quem recebeu
    (r"^PAGFOR|^PAGAMENTOAFORNECEDORES|^TEDPGTOFORNECEDORES|^PGTOFORNEC", "PAGFOR_LOTE"),
    (r"^TED(ENVIADA|PGTO)|^TEDDEVOLVIDA", "TED_ENVIADA"),
    (r"^DOC", "DOC"),
    (r"^PAGAMENTODEBOLETO|^PAGTOBOLETO|^PAGAMENTODETITULO", "BOLETO"),
    (r"^DEBITOPAGAMENTODESALARIO|PAGSAL", "FOLHA"),
    (r"^CRCOB", "COBRANCA_RECEBIDA"),
    (r"^PAGAMENTOCARTAO|^ANTECIPACAOCREDENCIADORA|STONE|CIELO|GETNET", "CARTAO"),
    (r"^(APLICACAO|RESGATE|APLIC|RESG)|^VENCIMENTOCDB", "APLICACAO_RESGATE"),
    (r"^TRANSFVALORP/CONTADIFTITULAR|DIFTITULAR|DIFERENTETITULAR", "TRANSF_TERCEIRO"),
    (r"MESMOTITULAR|^TRANSFERENCIAENTRECONTAS|^TRANSFVALORES", "TRANSFERENCIA"),
    (r"^DEP|^CHEQUEBCODEPOSITADO", "DEPOSITO"),
    (r"^SAQUE|^CHPAGO|^CHEQUE|^COMPENSACAOINTERNADECHEQUE", "CHEQUE_SAQUE"),
    (r"^TAR|^TARIFA|^IOF|^ENCARGOS|^JUROS", "TARIFA"),
    (r"TRIBUTO|^PGTO(TRIBUTOS|DARF|GPS|FGTS)|^DARF|^GPS", "TRIBUTO"),
    (r"^PAGAMENTOCONTA|^PAGTOCONTA|^CONTADE|^DEBITOAUTOMATICO|^DEBAUT", "CONTA_CONSUMO"),
    (r"^ESTORNO", "ESTORNO"),
]

# históricos cujo texto restante é o nome da contraparte
PREFIXOS_NOME = {
    "PIX_ENVIADO": r"^PIX ?ENVIAD[O0]",
    "TED_ENVIADA": r"^TED ?(ENVIADA|PGTO FORNECEDORES CIP)",
    "BOLETO": r"^PAGAMENTO DE BOLETO OUTROS BANCOS|^PAGAMENTO DE BOLETO|^PAGTO BOLETO",
    "CONTA_CONSUMO": r"^(PAGAMENTO CONTA|CONTA DE) [A-Z ]*?(EM CANAIS INTERNET|INTERNET)",
}


def sem_acento(s: str) -> str:
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()


def compacto(s: str) -> str:
    return re.sub(r"[^A-Z0-9/]", "", sem_acento(s).upper())


def tipo_de(descricao: str) -> str:
    c = compacto(descricao)
    for padrao, tipo in TIPOS:
        if re.search(padrao, c):
            return tipo
    return "OUTROS"


CONTAS_CLUBE = clube.CONTAS
# Contas do clube no Sicredi, registradas no balancete desde jan/2026.
CONTAS_CLUBE_SICREDI = clube.CONTAS_SICREDI
NOME_CLUBE_EXTRATO = clube.NOME_EXTRATO


def interna(descricao: str, tipo: str) -> bool:
    """Movimento entre contas do próprio clube ou entre conta e aplicação: não é receita nem despesa."""
    c = compacto(descricao)
    if tipo == "APLICACAO_RESGATE" or (CNPJ_CLUBE and CNPJ_CLUBE in c) or (NOME_CLUBE_EXTRATO and NOME_CLUBE_EXTRATO in c):
        return True
    if any(conta in c for conta in CONTAS_CLUBE_SICREDI):
        return True
    if tipo == "TRANSFERENCIA":
        return "MESMOTITULAR" in c or any(conta in c for conta in CONTAS_CLUBE)
    return False


@dataclass
class Contraparte:
    doc: str | None = None
    tipo_doc: str | None = None     # CPF, CNPJ, CNPJ_RAIZ
    nome: str | None = None


def contraparte(descricao: str, tipo: str) -> Contraparte:
    d = sem_acento(descricao).upper().replace(" | ", " ").strip()
    if tipo in ("PIX_RECEBIDO", "TED_RECEBIDA", "PIX_DEVOLUCAO"):
        m = re.search(r"(\d{14}|\d{11})\s*$", re.sub(r"(?<=\d)\s+(?=\d)", "", d))
        if m:
            n = m.group(1)
            return Contraparte(n, "CNPJ" if len(n) == 14 else "CPF")
    if tipo in ("TRANSF_TERCEIRO", "TRANSFERENCIA"):
        m = re.search(r"(PARA|DE):?\s*([\d.\-]{8,})", d)
        return Contraparte(None, None, f"CONTA {m.group(2)}") if m else Contraparte()
    padrao = PREFIXOS_NOME.get(tipo)
    if padrao:
        nome = re.sub(padrao, "", d).strip(" -|")
        nome = re.sub(r"^\d{4}\.\d{10,}\s*", "", nome).strip()   # conta de destino em TED/PAGFOR
        if not nome:
            return Contraparte()
        # MEI: o nome traz a raiz do CNPJ ("57 437 595 MATHEUS GRANDE")
        m = re.match(r"^(\d{2})\s?(\d{3})\s?(\d{3})\s+(.+)$", nome)
        if m:
            return Contraparte(m.group(1) + m.group(2) + m.group(3), "CNPJ_RAIZ", m.group(4).strip())
        m = re.match(r"^(\d{14})\s+(.+)$", nome)
        if m:
            return Contraparte(m.group(1), "CNPJ", m.group(2))
        return Contraparte(None, None, nome)
    return Contraparte()


# ----------------------------------------------------------------------------- OCR sem espaços
class Vocabulario:
    """Restaura espaços em históricos lidos por OCR ('PIXENVIADOLuaFigueiredo...'),
    usando os históricos e nomes que aparecem nos meses com texto digital."""

    def __init__(self, descricoes: list[str]):
        prefixos: Counter = Counter()
        self.nomes: dict[str, str] = {}
        for d in descricoes:
            partes = d.replace(" | ", " ").split()
            for k in range(1, min(len(partes), 6) + 1):
                prefixos[" ".join(partes[:k])] += 1
            self.nomes.setdefault(compacto(d), d.replace(" | ", " "))
            tipo = tipo_de(d)
            cp = contraparte(d, tipo)
            if cp.nome:
                self.nomes.setdefault(compacto(cp.nome), cp.nome)
        # prefixos de histórico do banco: frequentes e só com letras/barras
        self.prefixos = sorted(
            (p for p, n in prefixos.items() if n >= 15 and re.fullmatch(r"[A-Z/ .\-]+", p)),
            key=lambda p: -len(compacto(p)),
        )

    @staticmethod
    def _sem_o0(s: str) -> str:
        return s.replace("0", "O")

    def restaurar(self, ocr: str) -> str:
        c = compacto(ocr)
        if c in self.nomes:
            return self.nomes[c]
        for p in self.prefixos:
            cp = compacto(p)
            if self._sem_o0(c[: len(cp)]) == self._sem_o0(cp):
                # corta o texto original depois do prefixo (contando só os caracteres que o compacto mantém)
                n, i = 0, 0
                while i < len(ocr) and n < len(cp):
                    n += bool(compacto(ocr[i]))
                    i += 1
                resto_bruto = ocr[i:].strip()
                resto = self.nomes.get(compacto(resto_bruto))
                if resto is None:
                    # separa CamelCase ("LuaFigueiredodeJesus" -> "Lua Figueiredode Jesus") e dígitos
                    resto = re.sub(r"(?<=[a-z])(?=[A-Z])|(?<=[A-Za-z])(?=\d)|(?<=\d)(?=[A-Za-z])", " ", resto_bruto)
                return (p + " " + resto).strip()
        return ocr

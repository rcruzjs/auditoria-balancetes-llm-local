-- Balancete Analítico (contabilidade), separado dos movimentos bancários.

CREATE TABLE IF NOT EXISTS balancete (
    id                  serial PRIMARY KEY,
    documento_id        integer NOT NULL REFERENCES documentos(id) ON DELETE CASCADE,
    competencia         date NOT NULL,                 -- mês/ano do balancete
    pagina              integer NOT NULL,
    codigo              text,                          -- código da conta, ex.: 3155 (NULL nos totais gerais)
    descricao           text NOT NULL,                 -- a "string" da conta, ex.: Churrasqueiras - Aluguel
    tipo                text NOT NULL CHECK (tipo IN ('conta', 'grupo', 'total')),
    nivel               integer NOT NULL,
    grupo_codigo        text,                          -- grupo imediatamente acima
    grupo_descricao     text,
    saldo_anterior      numeric(14, 2),
    saldo_anterior_nat  char(1) CHECK (saldo_anterior_nat IN ('C', 'D')),
    debito              numeric(14, 2),
    credito             numeric(14, 2),
    saldo_atual         numeric(14, 2),
    saldo_atual_nat     char(1) CHECK (saldo_atual_nat IN ('C', 'D'))
);
CREATE INDEX IF NOT EXISTS ix_balancete_codigo ON balancete (codigo, competencia);

-- Contas que o usuário quer acompanhar (a "lista de strings"). Casamento pelo código da conta.
CREATE TABLE IF NOT EXISTS balancete_filtros (
    codigo     text PRIMARY KEY,
    descricao  text NOT NULL,          -- como o usuário escreveu
    ordem      integer NOT NULL,
    ativo      boolean NOT NULL DEFAULT true
);

CREATE OR REPLACE VIEW v_balancete_selecionado AS
SELECT d.arquivo AS relatorio, to_char(b.competencia, 'MM/YYYY') AS mes_ano, b.competencia,
       f.ordem, b.codigo, b.descricao AS string, b.tipo, b.grupo_descricao AS grupo,
       b.debito, b.credito, b.saldo_anterior, b.saldo_anterior_nat, b.saldo_atual, b.saldo_atual_nat, b.pagina
FROM balancete b
JOIN balancete_filtros f ON f.codigo = b.codigo AND f.ativo
JOIN documentos d ON d.id = b.documento_id;

-- Movimentos financeiros selecionados (extratos), só as strings pedidas.
-- A extração completa continua em `transacoes` (é o que prova que a leitura está completa);
-- esta visão apenas filtra. "variante" mostra a forma exata usada pelo banco.
CREATE OR REPLACE VIEW movimentos_financeiros AS
WITH t AS (
    SELECT t.*, d.arquivo,
           regexp_replace(upper(unaccent(t.descricao)), '[^A-Z0-9/]', '', 'g') AS c
    FROM transacoes t JOIN documentos d ON d.id = t.documento_id
    WHERE t.duplicada_de IS NULL
), m AS (
    SELECT t.*,
        CASE
            WHEN c ~ '^PIXRECEBID[O0]'                THEN 'Pix recebido'
            WHEN c ~ '^SAQUEDINHEIRO'                 THEN 'Saque dinheiro'
            WHEN c ~ '^(PAGAMENTOAFORNECEDORES|TEDPGTOFORNECEDORES|PAGFOR|PGTOFORNEC)' THEN 'Pagamento fornecedor'
            WHEN c ~ '^(CHEQUEEMITIDO|CHPAGO|COMPENSACAOINTERNADECHEQUE|CHEQUEBCODEPOSITADO)' THEN 'Cheque emitido'
            WHEN c ~ '^TEDENVIAD'                     THEN 'TED enviado'
            WHEN c ~ '^PIXENVIAD[O0]'                 THEN 'Pix enviado'
            WHEN c ~ '^(DEPCHEQUE|DEPDINHEIRO)'                                      THEN 'Dep cheque'
            WHEN c ~ '^(TAR|TARIFA)'                  THEN 'TAR'
        END AS string,
        CASE
            WHEN c ~ '^TEDPGTOFORNECEDORES' THEN 'TED PGTO FORNECEDORES'
            WHEN c ~ '^PAGFOR'              THEN 'PAGFOR PIX'
            WHEN c ~ '^PGTOFORNEC'          THEN 'PGTO FORNEC'
            WHEN c ~ '^CHPAGO'              THEN 'CH PAGO P/ CAIXA'
            WHEN c ~ '^COMPENSACAOINTERNA'  THEN 'COMPENSACAO INTERNA DE CHEQUE'
            WHEN c ~ '^CHEQUEBCODEPOSITADO' THEN 'CHEQUE BCO DEPOSITADO NO CAIXA (saída)'
            WHEN c ~ '^DEPDINHEIRO'         THEN 'DEP DINHEIRO (não é cheque)'
            WHEN c ~ '^TARIFA'              THEN 'TARIFA'
            ELSE 'principal'
        END AS variante
    FROM t
)
SELECT id, arquivo AS relatorio, pagina, to_char(competencia, 'MM/YYYY') AS mes_ano, competencia,
       data_mov, string, variante, valor,
       COALESCE(contraparte_nome, contraparte_doc) AS favorecido,
       CASE WHEN string = 'Pix recebido' THEN 'pagador'
            WHEN COALESCE(contraparte_nome, contraparte_doc) IS NOT NULL THEN 'recebedor' END AS papel,
       interna AS interno, descricao AS historico, origem, conta, documento_id, linha_y
FROM m WHERE string IS NOT NULL;

-- As contas acompanhadas (plano de contas do clube) ficam em db/init/900_contas_local.sql, fora do Git.
-- Exemplo do formato:
--   INSERT INTO balancete_filtros (codigo, descricao, ordem, natureza) VALUES
--     ('3164', 'Natação', 1, 'receita'), ('41546', 'Krav Maga', 2, 'despesa');

GRANT SELECT ON balancete, balancete_filtros, v_balancete_selecionado, movimentos_financeiros TO leitor;

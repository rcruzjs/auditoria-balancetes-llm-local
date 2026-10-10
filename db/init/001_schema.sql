-- Auditoria de balancetes: esquema do banco
-- Executado automaticamente na primeira subida do container "db".

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;    -- busca aproximada de nomes
CREATE EXTENSION IF NOT EXISTS unaccent;

-- ---------- Arquivos carregados ----------
CREATE TABLE documentos (
    id                serial PRIMARY KEY,
    arquivo           text NOT NULL,
    hash_sha256       char(64) NOT NULL UNIQUE,      -- impede carregar o mesmo PDF duas vezes
    competencia       date NOT NULL,                 -- 1º dia do mês do balancete
    paginas           integer NOT NULL,
    paginas_extrato   integer[] NOT NULL DEFAULT '{}',
    paginas_ocr       integer[] NOT NULL DEFAULT '{}',
    lancamentos       integer NOT NULL DEFAULT 0,
    duplicados        integer NOT NULL DEFAULT 0,
    conciliado        boolean,
    status            text NOT NULL DEFAULT 'carregado'
                      CHECK (status IN ('carregado', 'revisar', 'erro')),
    observacoes       text,
    carregado_em      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE contas_bancarias (
    conta     text PRIMARY KEY,
    banco     text NOT NULL DEFAULT 'Santander',
    agencia   text NOT NULL DEFAULT '4331',
    apelido   text
);

-- ---------- Categorias (editáveis) ----------
CREATE TABLE categorias (
    id         serial PRIMARY KEY,
    nome       text NOT NULL UNIQUE,
    grupo      text NOT NULL,          -- Eventos, Pessoal, Operacional, Receitas...
    descricao  text,
    cor        text
);

CREATE TABLE regras_categoria (
    id            serial PRIMARY KEY,
    padrao        text NOT NULL,       -- expressão regular (sem acento, maiúsculas) aplicada ao nome/descrição
    categoria_id  integer NOT NULL REFERENCES categorias(id) ON DELETE CASCADE,
    prioridade    integer NOT NULL DEFAULT 100,
    ativo         boolean NOT NULL DEFAULT true,
    criado_em     timestamptz NOT NULL DEFAULT now()
);

-- ---------- Contrapartes (quem pagou / quem recebeu) ----------
CREATE TABLE contrapartes (
    id               serial PRIMARY KEY,
    chave            text NOT NULL UNIQUE,  -- CPF/CNPJ (só dígitos) ou nome normalizado
    tipo             text NOT NULL CHECK (tipo IN ('CPF', 'CNPJ', 'CNPJ_RAIZ', 'NOME')),
    documento        text,                  -- CPF/CNPJ quando conhecido
    nome_extrato     text,                  -- como aparece no extrato (cortado em 25 caracteres)
    razao_social     text,
    nome_fantasia    text,
    cnae             text,
    cnae_descricao   text,
    data_abertura    date,
    situacao         text,
    municipio        text,
    uf               text,
    socios           jsonb,
    categoria_id     integer REFERENCES categorias(id),
    enriquecido_em   timestamptz,
    fonte            text,
    confianca        real,                  -- confiança do vínculo nome -> CNPJ
    observacoes      text
);
CREATE INDEX ix_contrapartes_nome_trgm ON contrapartes USING gin (nome_extrato gin_trgm_ops);

-- ---------- Transações (uma linha por lançamento do extrato) ----------
CREATE TABLE transacoes (
    id                bigserial PRIMARY KEY,
    documento_id      integer NOT NULL REFERENCES documentos(id) ON DELETE CASCADE,
    seq               integer NOT NULL,                -- ordem dentro do arquivo
    bloco             integer NOT NULL DEFAULT 0,      -- impressão/seção do extrato (para deduplicar)
    pagina            integer NOT NULL,
    linha_y           real,                            -- posição na página (para destacar no PDF)
    competencia       date NOT NULL,                   -- mês/ano do balancete
    data_mov          date NOT NULL,
    conta             text NOT NULL REFERENCES contas_bancarias(conta),
    tipo              text NOT NULL,                   -- PIX_RECEBIDO, PIX_ENVIADO, TED, BOLETO...
    direcao           char(1) NOT NULL CHECK (direcao IN ('E', 'S')),
    valor             numeric(14, 2) NOT NULL,         -- com sinal: entrada > 0, saída < 0
    interna           boolean NOT NULL DEFAULT false,  -- entre contas do clube / aplicação e resgate
    contraparte_id    integer REFERENCES contrapartes(id),
    contraparte_doc   text,                            -- CPF/CNPJ como veio no extrato
    contraparte_nome  text,
    descricao         text NOT NULL,                   -- histórico completo do banco
    documento_banco   text,
    saldo_apos        numeric(14, 2),
    origem            text NOT NULL CHECK (origem IN ('texto', 'ocr')),
    categoria_id      integer REFERENCES categorias(id),
    categoria_origem  text CHECK (categoria_origem IN ('regra', 'llm', 'manual')),
    duplicada_de      bigint REFERENCES transacoes(id),  -- mesma linha impressa em outro extrato
    hash_linha        text NOT NULL,
    UNIQUE (documento_id, seq)
);
CREATE INDEX ix_transacoes_data ON transacoes (data_mov);
CREATE INDEX ix_transacoes_tipo ON transacoes (tipo);
CREATE INDEX ix_transacoes_contraparte ON transacoes (contraparte_id);
CREATE INDEX ix_transacoes_categoria ON transacoes (categoria_id);
CREATE INDEX ix_transacoes_hash ON transacoes (hash_linha);

-- ---------- Conferência da extração contra o banco ----------
CREATE TABLE conciliacoes (
    id                  serial PRIMARY KEY,
    documento_id        integer NOT NULL REFERENCES documentos(id) ON DELETE CASCADE,
    conta               text,
    tipo                text NOT NULL CHECK (tipo IN ('saldo_corrido', 'resumo_mensal', 'balancete')),
    trechos_ok          integer,
    trechos_total       integer,
    creditos_extraidos  numeric(14, 2),
    creditos_banco      numeric(14, 2),
    debitos_extraidos   numeric(14, 2),
    debitos_banco       numeric(14, 2),
    ok                  boolean NOT NULL,
    detalhe             jsonb
);

-- ---------- Eventos do clube (Instagram, cadastro manual) ----------
CREATE TABLE eventos (
    id                serial PRIMARY KEY,
    nome              text NOT NULL,
    data_inicio       date NOT NULL,
    data_fim          date,
    tipo              text,          -- show, cultural, esportivo, social, infantil, gastronômico...
    local             text,
    publico_estimado  integer,
    link_instagram    text,
    observacoes       text,
    criado_em         timestamptz NOT NULL DEFAULT now()
);

-- ---------- DRE por conta contábil (fase seguinte) ----------
CREATE TABLE dre_lancamentos (
    id             serial PRIMARY KEY,
    documento_id   integer NOT NULL REFERENCES documentos(id) ON DELETE CASCADE,
    competencia    date NOT NULL,
    classificacao  text NOT NULL,     -- ex.: 4-10-07-03
    codigo         text,
    descricao      text NOT NULL,     -- ex.: Eventos Sociais e Artísticos
    grupo          text,              -- ex.: Diretoria Social e Cultural
    valor          numeric(14, 2) NOT NULL,
    natureza       char(1) CHECK (natureza IN ('C', 'D'))
);

-- ---------- Auditoria do chat ----------
CREATE TABLE consultas_log (
    id          serial PRIMARY KEY,
    pergunta    text NOT NULL,
    sql_gerado  text,
    modelo      text,
    linhas      integer,
    erro        text,
    criado_em   timestamptz NOT NULL DEFAULT now()
);

-- ---------- Visões para análise ----------
-- Movimentos reais: sem duplicatas e sem transferências internas
CREATE VIEW v_movimentos AS
SELECT t.*, c.nome AS categoria, c.grupo AS categoria_grupo,
       cp.razao_social, cp.cnae_descricao,
       date_trunc('month', t.data_mov)::date AS mes
FROM transacoes t
LEFT JOIN categorias c ON c.id = t.categoria_id
LEFT JOIN contrapartes cp ON cp.id = t.contraparte_id
WHERE t.duplicada_de IS NULL AND NOT t.interna;

CREATE VIEW v_resumo_mensal AS
SELECT mes,
       sum(valor) FILTER (WHERE valor > 0) AS entradas,
       -sum(valor) FILTER (WHERE valor < 0) AS saidas,
       sum(valor) AS resultado,
       count(*) AS lancamentos
FROM v_movimentos GROUP BY mes ORDER BY mes;

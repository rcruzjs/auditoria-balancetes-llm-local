-- Sugestões de categoria feitas pelo LLM, por recebedor, aguardando revisão humana.
CREATE TABLE IF NOT EXISTS sugestoes_categoria (
    id              serial PRIMARY KEY,
    contraparte_id  integer NOT NULL REFERENCES contrapartes(id) ON DELETE CASCADE,
    categoria_id    integer REFERENCES categorias(id),     -- NULL = indeterminado
    confianca       real,
    motivo          text,
    modelo          text NOT NULL,
    status          text NOT NULL DEFAULT 'pendente'
                    CHECK (status IN ('pendente', 'aceita', 'corrigida', 'rejeitada')),
    revisado_em     timestamptz,
    criado_em       timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_sugestoes_contraparte ON sugestoes_categoria (contraparte_id, criado_em DESC);

INSERT INTO categorias (nome, grupo, descricao, cor)
VALUES ('Atividades esportivas e escolinhas', 'Operacional',
        'Professores, escolinhas e repasses de atividades (natação, ginástica, tênis, vela)', '#ADB5BD'),
       ('Seguros e saúde', 'Pessoal', 'Plano de saúde, seguros, benefícios', '#6C757D'),
       ('Transporte', 'Operacional', 'Fretes, transporte, combustível', '#ADB5BD'),
       ('Comunicação e marketing', 'Operacional', 'Publicidade, gráfica, agência, redes sociais', '#ADB5BD')
ON CONFLICT (nome) DO NOTHING;

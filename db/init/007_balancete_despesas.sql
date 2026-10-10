-- Contas de despesa acompanhadas (2ª lista do usuário) e natureza receita/despesa.
-- Nomes se repetem entre receita e despesa (ex.: Krav Maga 41532 receita x 41546 despesa): o código decide.

ALTER TABLE balancete_filtros ADD COLUMN IF NOT EXISTS natureza text NOT NULL DEFAULT 'receita'
    CHECK (natureza IN ('receita', 'despesa'));

-- As contas acompanhadas (plano de contas do clube) ficam em db/init/900_contas_local.sql, fora do Git.
-- Exemplo do formato:
--   INSERT INTO balancete_filtros (codigo, descricao, ordem, natureza) VALUES
--     ('3164', 'Natação', 1, 'receita'), ('41546', 'Krav Maga', 2, 'despesa');

-- natureza no fim (CREATE OR REPLACE VIEW só permite acrescentar colunas no final)
CREATE OR REPLACE VIEW v_balancete_selecionado AS
SELECT d.arquivo AS relatorio, to_char(b.competencia, 'MM/YYYY') AS mes_ano, b.competencia,
       f.ordem, b.codigo, b.descricao AS string, b.tipo, b.grupo_descricao AS grupo,
       b.debito, b.credito, b.saldo_anterior, b.saldo_anterior_nat, b.saldo_atual, b.saldo_atual_nat, b.pagina,
       f.natureza
FROM balancete b
JOIN balancete_filtros f ON f.codigo = b.codigo AND f.ativo
JOIN documentos d ON d.id = b.documento_id;

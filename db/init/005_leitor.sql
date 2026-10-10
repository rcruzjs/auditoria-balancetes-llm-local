-- Usuário somente leitura para o chat (o SQL gerado pelo LLM roda com ele).
-- A senha é definida pelo script de setup a partir do .env (LEITOR_PASSWORD).
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'leitor') THEN
    CREATE ROLE leitor LOGIN;
  END IF;
END $$;
GRANT CONNECT ON DATABASE auditoria TO leitor;
GRANT USAGE ON SCHEMA public TO leitor;
GRANT SELECT ON v_movimentos, v_resumo_mensal, transacoes, documentos, categorias, contrapartes,
               eventos, conciliacoes, contas_bancarias, dre_lancamentos TO leitor;
ALTER ROLE leitor SET statement_timeout = '15s';
ALTER ROLE leitor SET default_transaction_read_only = on;

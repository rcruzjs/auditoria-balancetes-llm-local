"""Conexão com o PostgreSQL do projeto (configuração no arquivo .env)."""
import os
from pathlib import Path

import psycopg
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")


def url() -> str:
    return os.environ.get("DATABASE_URL") or (
        f"postgresql://{os.environ.get('POSTGRES_USER', 'auditoria')}:{os.environ['POSTGRES_PASSWORD']}"
        f"@127.0.0.1:{os.environ.get('POSTGRES_PORT', '5433')}/{os.environ.get('POSTGRES_DB', 'auditoria')}"
    )


def conectar() -> psycopg.Connection:
    return psycopg.connect(url())

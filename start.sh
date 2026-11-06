#!/bin/bash
set -e

cd /opt/knowledge-base
source .venv/bin/activate

python -m knowledge_base.infrastructure.db_migrate
exec uvicorn main:app --host 0.0.0.0 --port 9007
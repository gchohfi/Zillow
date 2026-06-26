#!/usr/bin/env bash
# Roda uma varredura. Pensado para ser chamado pelo cron de hora em hora.
#
# Exemplo de crontab (rode `crontab -e` e cole a linha; ajuste o caminho):
#   0 * * * * /caminho/para/orlando-land-detector/run.sh >> /caminho/para/orlando-land-detector/run.log 2>&1
#
# A cada execução ele busca listagens novas, calcula viabilidade, acrescenta as
# viáveis no CSV e dispara os alertas configurados.

set -euo pipefail
cd "$(dirname "$0")"

# Usa a venv local se existir.
if [ -d ".venv" ]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

echo "===== $(date '+%Y-%m-%d %H:%M:%S') ====="
python -m src.main "$@"

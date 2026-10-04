#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
export PATH="/usr/local/bin:/opt/homebrew/bin:$PATH"
if ! command -v docker >/dev/null; then
  echo 'Установите Docker Desktop, затем повторите запуск.'; exit 1
fi
if ! docker info >/dev/null 2>&1; then
  if [[ "$(uname)" == Darwin ]]; then open -a Docker; fi
  echo 'Ожидаю запуск Docker Desktop…'
  ready=0
  for ((i=0;i<120;i++)); do
    if docker info >/dev/null 2>&1; then ready=1; break; fi
    sleep 1
  done
  if [[ "$ready" == 0 ]]; then echo 'Docker не запустился. Откройте Docker Desktop и повторите.'; exit 1; fi
fi
case "${1:-start}" in
  start)
    docker compose up -d --build --wait
    port="$(docker compose port app 8083 | sed 's/.*://')"
    echo "Сервис готов: http://localhost:$port"
    echo 'Логин: demo. Пароль по умолчанию: demo12345 (или DEMO_PASSWORD из .env).'
    if [[ "$(uname)" == Darwin ]]; then open "http://localhost:$port"; fi
    ;;
  stop) docker compose stop; echo 'Остановлено. Данные сохранены.' ;;
  tests)
    docker compose up -d --wait db
    docker compose exec -T db sh -c 'psql -U app -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname = '\''evgenii_nevokshenov_test'\''" | grep -q 1 || psql -U app -d postgres -c "CREATE DATABASE evgenii_nevokshenov_test"'
    docker compose run --rm app sh -c 'export DATABASE_URL="${DATABASE_URL%/*}/evgenii_nevokshenov_test"; python -m pytest -q' 
    ;;
  *) echo 'Использование: bash scripts/control.sh start|stop|tests'; exit 1 ;;
esac

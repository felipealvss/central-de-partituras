#!/usr/bin/env bash
# Abre a Central de Partituras: inicia o servidor local (se ainda não estiver rodando) e abre a janela.
# O servidor fecha sozinho alguns minutos depois que a janela é fechada e a fila de conversão termina.
AQUI="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
CONV="$AQUI/conversor"
EST="$AQUI/.estado"
PY="$CONV/.venv/bin/python"

avisar() {
  if command -v zenity >/dev/null; then zenity --error --title="Central de Partituras" --text="$1" 2>/dev/null
  else echo "$1" >&2; fi
}

[ -x "$PY" ] || { avisar "A Central ainda não foi instalada. Rode: $CONV/instalar.sh"; exit 1; }
mkdir -p "$EST"

url() {  # http://127.0.0.1:PORTA/?t=FICHA, a partir de .estado/servidor.json
  "$PY" -I -c "import json,sys; d=json.load(open(sys.argv[1])); print(f\"http://127.0.0.1:{d['porta']}/?t={d['token']}\")" "$EST/servidor.json" 2>/dev/null
}
ativo() {
  [ -f "$EST/servidor.json" ] || return 1
  local u; u="$(url)" || return 1
  curl -fs --max-time 1 "${u%%/\?t=*}/api/ping" >/dev/null 2>&1
}

if ! ativo; then
  (cd "$CONV" && nohup "$PY" -m partituras.servidor >"$EST/servidor.log" 2>&1 &)
  for _ in $(seq 1 80); do ativo && break; sleep 0.25; done
fi
ativo || { avisar "Não consegui iniciar a Central. Veja $EST/servidor.log"; exit 1; }

NAVEGADOR="$(command -v google-chrome || command -v chromium-browser || command -v chromium)"
if [ -n "$NAVEGADOR" ]; then
  exec "$NAVEGADOR" --user-data-dir="$EST/chrome" --no-first-run --no-default-browser-check \
       --class=CentralPartituras --app="$(url)" >/dev/null 2>&1
else
  exec xdg-open "$(url)"
fi

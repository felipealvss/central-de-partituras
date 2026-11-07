#!/usr/bin/env bash
# Instala a Central de Partituras dentro desta pasta (nada é instalado no sistema).
#   - ambiente Python (.venv): Pillow, pillow-heif (fotos HEIC), numpy, homr (reconhecimento para fotos de
#     celular; baixa os modelos na primeira conversão), Flask e waitress (a interface local)
#   - Audiveris (reconhecimento de partitura), extraído do pacote oficial para Linux
#   - dados de OCR do Tesseract (inglês), para o Audiveris ler títulos e indicações de texto
#   - opcional: atalho "Central de Partituras" no menu de aplicativos (~/.local/share/applications)
# Uso: ./instalar.sh [--atalho | --sem-atalho]
# Para usar um .deb já baixado: AUDIVERIS_DEB=/caminho/Audiveris.deb ./instalar.sh
set -euo pipefail
AQUI="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
RAIZ="$(dirname "$AQUI")"
VERSAO="${AUDIVERIS_VERSAO:-5.11.0}"
ATALHO="${1:-perguntar}"

for c in python3 mscore magick pdftoppm ar tar curl; do
  command -v "$c" >/dev/null || { echo "Falta o programa '$c'. Instale-o antes de continuar."; exit 1; }
done
command -v google-chrome >/dev/null || command -v chromium >/dev/null || command -v chromium-browser >/dev/null || \
  echo "Aviso: sem Google Chrome/Chromium a interface abre no navegador padrão."
command -v zenity >/dev/null || echo "Aviso: sem o zenity, a escolha de pasta de saída não abre a janela do sistema."

echo "1/4 Ambiente Python..."
[ -x "$AQUI/.venv/bin/python" ] || python3 -m venv "$AQUI/.venv"
"$AQUI/.venv/bin/pip" install -q --disable-pip-version-check pillow pillow-heif numpy homr flask waitress

echo "2/4 Audiveris $VERSAO..."
if [ ! -x "$AQUI/audiveris/opt/audiveris/bin/Audiveris" ]; then
  TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
  DEB="${AUDIVERIS_DEB:-}"
  if [ -z "$DEB" ]; then
    DEB="$TMP/audiveris.deb"
    curl -fL --progress-bar -o "$DEB" "https://github.com/Audiveris/audiveris/releases/download/$VERSAO/Audiveris-$VERSAO-ubuntu24.04-x86_64.deb"
  fi
  (cd "$TMP" && ar x "$DEB" && mkdir -p "$AQUI/audiveris" && tar -xf data.tar.* -C "$AQUI/audiveris")
fi

echo "3/4 Dados de OCR..."
mkdir -p "$AQUI/tessdata"
[ -s "$AQUI/tessdata/eng.traineddata" ] || curl -fL --progress-bar -o "$AQUI/tessdata/eng.traineddata" \
  "https://github.com/tesseract-ocr/tessdata/raw/main/eng.traineddata"

chmod +x "$AQUI/converter" "$RAIZ/abrir-conversor.sh"

echo "4/4 Atalho no menu de aplicativos..."
if [ "$ATALHO" = "perguntar" ] && [ -t 0 ]; then
  read -r -p "Criar o atalho 'Central de Partituras' no menu de aplicativos? [S/n] " resp
  case "${resp:-s}" in [nN]*) ATALHO="--sem-atalho" ;; *) ATALHO="--atalho" ;; esac
fi
if [ "$ATALHO" = "--atalho" ]; then
  DESTINO="$HOME/.local/share/applications/central-partituras.desktop"
  mkdir -p "$(dirname "$DESTINO")"
  cat > "$DESTINO" <<EOF
[Desktop Entry]
Type=Application
Name=Central de Partituras
Comment=Converte fotos e PDFs de partituras em arquivos do MuseScore
Exec="$RAIZ/abrir-conversor.sh"
Icon=$AQUI/partituras/static/icone.svg
Terminal=false
Categories=AudioVideo;Audio;Music;
StartupWMClass=CentralPartituras
EOF
  command -v update-desktop-database >/dev/null && update-desktop-database "$(dirname "$DESTINO")" >/dev/null 2>&1 || true
  echo "Atalho criado: $DESTINO"
else
  echo "Atalho não criado (rode ./instalar.sh --atalho para criar depois)."
fi

echo "Pronto. Abra a Central pelo menu de aplicativos ou com: $RAIZ/abrir-conversor.sh"

#!/usr/bin/env bash
# Instala as dependências do conversor dentro desta pasta (nada é instalado no sistema).
#   - ambiente Python (.venv) com Pillow, pillow-heif (fotos HEIC), numpy e homr (reconhecimento
#     para fotos de celular; baixa os modelos na primeira conversão)
#   - Audiveris (reconhecimento de partitura), extraído do pacote oficial para Linux
#   - dados de OCR do Tesseract (inglês), para o Audiveris ler títulos e indicações de texto
# Para usar um .deb já baixado: AUDIVERIS_DEB=/caminho/Audiveris.deb ./instalar.sh
set -euo pipefail
AQUI="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
VERSAO="${AUDIVERIS_VERSAO:-5.11.0}"

for c in python3 mscore magick pdftoppm ar tar curl; do
  command -v "$c" >/dev/null || { echo "Falta o programa '$c'. Instale-o antes de continuar."; exit 1; }
done

echo "1/3 Ambiente Python..."
[ -x "$AQUI/.venv/bin/python" ] || python3 -m venv "$AQUI/.venv"
"$AQUI/.venv/bin/pip" install -q --disable-pip-version-check pillow pillow-heif numpy homr

echo "2/3 Audiveris $VERSAO..."
if [ ! -x "$AQUI/audiveris/opt/audiveris/bin/Audiveris" ]; then
  TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
  DEB="${AUDIVERIS_DEB:-}"
  if [ -z "$DEB" ]; then
    DEB="$TMP/audiveris.deb"
    curl -fL --progress-bar -o "$DEB" "https://github.com/Audiveris/audiveris/releases/download/$VERSAO/Audiveris-$VERSAO-ubuntu24.04-x86_64.deb"
  fi
  (cd "$TMP" && ar x "$DEB" && mkdir -p "$AQUI/audiveris" && tar -xf data.tar.* -C "$AQUI/audiveris")
fi

echo "3/3 Dados de OCR..."
mkdir -p "$AQUI/tessdata"
[ -s "$AQUI/tessdata/eng.traineddata" ] || curl -fL --progress-bar -o "$AQUI/tessdata/eng.traineddata" \
  "https://github.com/tesseract-ocr/tessdata/raw/main/eng.traineddata"

chmod +x "$AQUI/converter"
echo "Pronto. Exemplo: $AQUI/converter foto1.heic foto2.heic -o musica.mscz --pdf"

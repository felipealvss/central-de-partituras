#!/usr/bin/env bash
# Instala a Central de Partituras dentro desta pasta (nada é instalado no sistema).
#   - ambiente Python (.venv): Pillow, pillow-heif (fotos HEIC), numpy, homr (reconhecimento para fotos de
#     celular; baixa os modelos na primeira conversão), Flask e waitress (a interface local)
#   - Audiveris (reconhecimento de partitura), extraído do pacote oficial para Linux
#   - dados de OCR do Tesseract (inglês), para o Audiveris ler títulos e indicações de texto
#   - opcional: atalho "Central de Partituras" no menu de aplicativos (~/.local/share/applications)
#   - opcional, com --audio: o modo de áudio (transcrever sax, trompete e trombone de uma gravação).
#     Cria o .venv-audio (Python 3.12 com PyTorch, librosa, music21, Beat This! e yt-dlp, pelo uv) e baixa os
#     modelos para modelos-audio/, conferindo o SHA-256 de cada arquivo. Ocupa cerca de 7,5 GB e precisa
#     de uns 12 GB livres durante a instalação. Precisa do ffmpeg; o aria2c (se houver) acelera os downloads.
# Uso: ./instalar.sh [--atalho | --sem-atalho] [--audio] [--atualizar-yt-dlp]
#   --atualizar-yt-dlp sozinho só atualiza o yt-dlp (importar por link quebra quando o site muda).
# Para usar um .deb já baixado: AUDIVERIS_DEB=/caminho/Audiveris.deb ./instalar.sh
set -euo pipefail
AQUI="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
RAIZ="$(dirname "$AQUI")"
VERSAO="${AUDIVERIS_VERSAO:-5.11.0}"
UV_VERSAO=0.13.7
ATALHO=perguntar
AUDIO=0
YT_DLP=0
for arg in "$@"; do
  case "$arg" in
    --atalho|--sem-atalho) ATALHO="$arg" ;;
    --audio) AUDIO=1 ;;
    --atualizar-yt-dlp) YT_DLP=1 ;;
    -h|--ajuda|--help) sed -n '2,/^set -euo/p' "$0" | sed '$d; s/^# \{0,1\}//'; exit 0 ;;
    *) echo "Opção desconhecida: $arg (veja ./instalar.sh --ajuda)"; exit 2 ;;
  esac
done
PYA="$AQUI/.venv-audio/bin/python"

# uv dentro do projeto: o Python 3.12, o cache e as rodas baixadas ficam em .uv/ (o cache e as rodas são
# apagados no fim; o Python fica, porque o .venv-audio usa ele). As bibliotecas são baixadas pelo
# partituras/audio/instalar.py (aria2c ou curl) e o uv instala sem rede; só o yt-dlp vem pelo uv, da internet.
preparar_uv() {
  export UV_CACHE_DIR="$AQUI/.uv/cache" UV_PYTHON_INSTALL_DIR="$AQUI/.uv/python" UV_PYTHON_PREFERENCE=only-managed
  export UV_NO_CONFIG=1 UV_HTTP_TIMEOUT=60 PYTHONUNBUFFERED=1
  "$AQUI/.venv/bin/pip" install -q --disable-pip-version-check "uv==$UV_VERSAO"
  UV="$AQUI/.venv/bin/uv"
}
atualizar_yt_dlp() {
  "$UV" pip install --python "$PYA" --upgrade-package yt-dlp --upgrade-package yt-dlp-ejs "yt-dlp[default]" &&
    echo "  yt-dlp $("$AQUI/.venv-audio/bin/yt-dlp" --version)"
}

if [ "$YT_DLP" = 1 ] && [ "$AUDIO" = 0 ]; then
  [ -x "$PYA" ] || { echo "O modo de áudio não está instalado: rode ./instalar.sh --audio"; exit 1; }
  echo "Atualizando o yt-dlp..."
  preparar_uv
  atualizar_yt_dlp
  rm -rf "$UV_CACHE_DIR"
  exit 0
fi

for c in python3 mscore magick pdftoppm ar tar curl; do
  command -v "$c" >/dev/null || { echo "Falta o programa '$c'. Instale-o antes de continuar."; exit 1; }
done
if [ "$AUDIO" = 1 ]; then
  for c in ffmpeg ffprobe; do
    command -v "$c" >/dev/null || { echo "O modo de áudio precisa do '$c' (no Fedora: sudo dnf install ffmpeg-free)."; exit 1; }
  done
  livre=$(df -Pk "$AQUI" | awk 'NR==2 {print int($4 / 1048576)}')
  [ "$livre" -ge 12 ] || echo "Aviso: só $livre GB livres; a instalação do modo de áudio precisa de uns 12 GB."
fi
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
DESTINO="$HOME/.local/share/applications/central-partituras.desktop"
if [ "$ATALHO" = "perguntar" ] && [ "$AUDIO" = 1 ] && [ -f "$DESTINO" ]; then
  ATALHO=manter
fi
if [ "$ATALHO" = "perguntar" ] && [ -t 0 ]; then
  read -r -p "Criar o atalho 'Central de Partituras' no menu de aplicativos? [S/n] " resp
  case "${resp:-s}" in [nN]*) ATALHO="--sem-atalho" ;; *) ATALHO="--atalho" ;; esac
fi
if [ "$ATALHO" = "--atalho" ]; then
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
elif [ "$ATALHO" = "manter" ]; then
  echo "Atalho já existe: $DESTINO"
else
  echo "Atalho não criado (rode ./instalar.sh --atalho para criar depois)."
fi

if [ "$AUDIO" = 1 ]; then
  echo "Modo de áudio..."
  preparar_uv
  echo "Áudio 1/5 Python 3.12 (uv $UV_VERSAO)..."
  if [ ! -x "$PYA" ]; then
    rm -rf "$AQUI/.venv-audio"
    "$UV" venv -q --python 3.12 "$AQUI/.venv-audio"
  fi
  echo "Áudio 2/5 Download das bibliotecas (na 1ª vez, uns 3,2 GB: PyTorch com as bibliotecas da NVIDIA)..."
  RODAS="$AQUI/.uv/rodas"
  mkdir -p "$RODAS"
  (cd "$AQUI" && "$AQUI/.venv/bin/python" -m partituras.audio.instalar rodas "$AQUI/requisitos-audio.txt" "$RODAS" \
    --python "$PYA")
  echo "Áudio 3/5 Instalação das bibliotecas (sem rede, conferidas pelo hash) e do yt-dlp..."
  "$UV" pip install -q --offline --no-index --find-links "$RODAS" --python "$PYA" -r "$AQUI/requisitos-audio.txt"
  atualizar_yt_dlp || echo "  Aviso: o yt-dlp não foi instalado agora; importar por link fica indisponível até rodar" \
    "./instalar.sh --atualizar-yt-dlp."
  echo "Áudio 4/5 Modelos (separação e pulsação, cerca de 1,45 GB)..."
  (cd "$AQUI" && "$AQUI/.venv/bin/python" -m partituras.audio.instalar modelos)
  echo "Áudio 5/5 Node.js (para importar por link)..."
  (cd "$AQUI" && "$AQUI/.venv/bin/python" -m partituras.audio.instalar node)
  rm -rf "$RODAS" "$UV_CACHE_DIR"
  "$PYA" -c 'import torch
if torch.cuda.is_available():
    p = torch.cuda.get_device_properties(0)
    print(f"  Placa de vídeo: {p.name} ({p.total_memory / 2**30:.1f} GB)")
else:
    print("  Sem placa de vídeo NVIDIA utilizável: a separação vai usar o processador (bem mais lenta).")' || true
  echo "Modo de áudio instalado."
fi

echo "Pronto. Abra a Central pelo menu de aplicativos ou com: $RAIZ/abrir-conversor.sh"

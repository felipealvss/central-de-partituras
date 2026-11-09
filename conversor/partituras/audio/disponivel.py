"""O modo de áudio está pronto para uso? Só biblioteca padrão (o servidor importa este módulo)."""
import os
import shutil
from pathlib import Path

from .. import caminhos


def node():
    """Caminho do Node.js para o yt-dlp. O instalador grava o caminho absoluto, porque o atalho do menu não
    herda o PATH do terminal (gerenciadores como o fnm só existem dentro dele)."""
    gravado = caminhos.MODELOS_AUDIO / 'node.txt'
    if gravado.exists():
        p = Path(gravado.read_text(encoding='utf-8').strip())
        if p.is_file() and os.access(p, os.X_OK):
            return str(p)
    return shutil.which('node')


def yt_dlp():
    p = caminhos.PY_AUDIO.parent / 'yt-dlp'
    return str(p) if p.exists() else None


def estado():
    """{'pronto': bool, 'falta': [...], 'link': bool} — 'link' diz se a importação por link funciona."""
    falta = []
    if not caminhos.PY_AUDIO.exists():
        falta.append('o ambiente de áudio (rode conversor/instalar.sh --audio)')
    if not (caminhos.MODELOS_AUDIO / '.verificado').exists():
        falta.append('os modelos de áudio (rode conversor/instalar.sh --audio)')
    for programa in ('ffmpeg', 'ffprobe'):
        if not shutil.which(programa):
            falta.append(f'o {programa} (pacote ffmpeg do sistema)')
    return {'pronto': not falta, 'falta': falta, 'link': bool(not falta and yt_dlp() and node())}

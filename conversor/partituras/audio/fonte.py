"""Áudio de entrada: extensões aceitas, identificação pelo conteúdo e características lidas pelo ffprobe.
Só biblioteca padrão (o servidor importa este módulo)."""
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

from ..erros import ErroConversao

EXTENSOES = ('.mp3', '.wav', '.flac', '.ogg', '.oga', '.opus', '.m4a', '.aac', '.webm', '.mka', '.mp4',
             '.aif', '.aiff', '.wma')
SEM_PERDAS = {'flac', 'alac', 'wavpack', 'tta', 'ape', 'truehd', 'mlp'}


def e_audio(nome):
    return Path(str(nome)).suffix.lower() in EXTENSOES


def identificar(caminho):
    """Hash do conteúdo (16 caracteres), para reconhecer o mesmo áudio importado de novo."""
    h = hashlib.sha256()
    with open(caminho, 'rb') as f:
        for bloco in iter(lambda: f.read(1 << 20), b''):
            h.update(bloco)
    return h.hexdigest()[:16]


def sondar(caminho, timeout=60):
    """Características do áudio: codec, taxa, canais, kb/s, duração (s) e se o formato tem perdas."""
    ffprobe = shutil.which('ffprobe')
    if not ffprobe:
        raise ErroConversao('O ffprobe (pacote ffmpeg) não está instalado.')
    r = subprocess.run([ffprobe, '-v', 'error', '-select_streams', 'a:0',
                        '-show_entries', 'stream=codec_name,sample_rate,channels,bit_rate:format=duration,bit_rate',
                        '-of', 'json', str(caminho)], capture_output=True, text=True, timeout=timeout)
    try:
        dados = json.loads(r.stdout or '{}')
    except json.JSONDecodeError:
        dados = {}
    fluxos = dados.get('streams') or []
    if r.returncode != 0 or not fluxos:
        raise ErroConversao(f'"{Path(caminho).name}" não tem áudio que o ffmpeg consiga ler.')
    s, fmt = fluxos[0], dados.get('format') or {}
    codec = s.get('codec_name') or '?'
    bits = s.get('bit_rate') or fmt.get('bit_rate')
    return {'codec': codec, 'taxa': int(s.get('sample_rate') or 0), 'canais': int(s.get('channels') or 0),
            'kbps': round(int(bits) / 1000) if str(bits or '').isdigit() else None,
            'duracao': round(float(fmt.get('duration') or 0), 2),
            'com_perdas': not (codec in SEM_PERDAS or codec.startswith('pcm_'))}

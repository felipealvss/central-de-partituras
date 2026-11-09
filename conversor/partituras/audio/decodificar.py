"""Original (qualquer formato que o ffmpeg leia) → audio/mistura.flac: estéreo, 44,1 kHz, 24 bits.

O ffmpeg decodifica uma vez na taxa original e o soxr (qualidade alta) converte para 44,1 kHz, como no piloto.
A mistura é a referência de tempo de tudo (trechos, A/B): tocar o original com perdas pode deslocar alguns
milissegundos por causa do atraso do codificador. Ambiente de áudio.
"""
import os
import shutil
import uuid
from pathlib import Path

from .. import processos
from ..erros import ErroConversao

SR = 44100


def para_mistura(original, destino, timeout=600):
    import soundfile as sf
    import soxr
    ffmpeg = shutil.which('ffmpeg')
    if not ffmpeg:
        raise ErroConversao('O ffmpeg não está instalado.')
    destino = Path(destino)
    tmp_wav = destino.parent / f'.decodificando-{uuid.uuid4().hex[:8]}.wav'
    tmp_flac = tmp_wav.with_suffix('.flac')
    try:
        processos.rodar([ffmpeg, '-nostdin', '-v', 'error', '-y', '-i', str(original), '-map', '0:a:0', '-ac', '2',
                         '-c:a', 'pcm_f32le', str(tmp_wav)], timeout=timeout, nome='ffmpeg')
        audio, sr = sf.read(str(tmp_wav), dtype='float32', always_2d=True)
        if sr != SR:
            audio = soxr.resample(audio, sr, SR, quality='HQ')
        sf.write(str(tmp_flac), audio, SR, subtype='PCM_24')
        os.replace(tmp_flac, destino)
    finally:
        tmp_wav.unlink(missing_ok=True)
        tmp_flac.unlink(missing_ok=True)
    return destino

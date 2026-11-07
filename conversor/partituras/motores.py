"""Os dois motores de reconhecimento: homr (fotos de celular) e Audiveris (scans, dinâmicas e textos)."""
import os
import shutil
import sys
from pathlib import Path

from . import caminhos
from . import musicxml as mx
from .erros import ErroConversao
from .processos import rodar

MOTORES = ('homr', 'audiveris')


def executavel_homr():
    return Path(sys.executable).parent / 'homr'


def env_audiveris():
    """Dados de OCR desta pasta e configuração/logs do Audiveris dentro de .estado (nada em ~/.config)."""
    base = caminhos.ESTADO / 'audiveris'
    env = dict(os.environ, TESSDATA_PREFIX=str(caminhos.TESSDATA))
    for var, sub in (('XDG_CONFIG_HOME', 'config'), ('XDG_DATA_HOME', 'dados'), ('XDG_CACHE_HOME', 'cache')):
        pasta = base / sub
        pasta.mkdir(parents=True, exist_ok=True)
        env[var] = str(pasta)
    env.setdefault('LANG', 'C.UTF-8')
    return env


def disponibilidade():
    return {
        'homr': executavel_homr().exists(),
        'audiveris': caminhos.AUDIVERIS.exists(),
        'ocr': (caminhos.TESSDATA / 'eng.traineddata').exists(),
        'mscore': bool(shutil.which('mscore')),
        'magick': bool(shutil.which('magick')),
        'pdftoppm': bool(shutil.which('pdftoppm')),
        'zenity': bool(shutil.which('zenity')),
    }


def rodar_homr(imagens, pasta, progresso, timeout_pagina=1500):
    """homr trabalha página a página. Na primeira execução baixa os modelos (alguns minutos)."""
    homr = executavel_homr()
    if not homr.exists():
        raise ErroConversao('O homr não está instalado. Rode conversor/instalar.sh.')
    pasta = Path(pasta)
    arvores = []
    for i, (nome, im) in enumerate(imagens, 1):
        progresso('reconhecendo', f'homr: página {i} de {len(imagens)}', i, len(imagens))
        img = pasta / f'homr-pagina{i:02d}.jpg'
        im.convert('RGB').save(img, quality=95)
        log = pasta / f'homr-pagina{i:02d}.log'
        rodar([homr, img.name], timeout=timeout_pagina, log=log, cwd=pasta, nome='homr')
        xml = img.with_suffix('.musicxml')
        if not xml.exists():
            raise ErroConversao(f'O homr não reconheceu a página {i} ({nome}). Detalhes em {log.name}.')
        arvores.append(mx.ler(xml))
    return arvores


def rodar_audiveris(pdf, pasta, progresso, timeout=2400):
    if not caminhos.AUDIVERIS.exists():
        raise ErroConversao('O Audiveris não está instalado. Rode conversor/instalar.sh.')
    pasta = Path(pasta)
    saida = pasta / 'audiveris'
    saida.mkdir(exist_ok=True)
    progresso('reconhecendo', 'Audiveris: reconhecendo todas as páginas', None, None)
    rodar([caminhos.AUDIVERIS, '-batch', '-export', '-output', saida, '--', pdf],
          timeout=timeout, log=pasta / 'audiveris.log', env=env_audiveris(), nome='Audiveris')
    mxls = sorted(saida.glob('*.mxl'))
    if not mxls:
        raise ErroConversao('O Audiveris não gerou partitura. Detalhes em audiveris.log.')
    omr = next(iter(saida.glob('*.omr')), None)
    return [mx.ler(m) for m in mxls], omr

"""Conversões com o MuseScore instalado no sistema (mscore), sem abrir janela."""
import os
import shutil
from pathlib import Path

from .erros import ErroConversao
from .processos import rodar


def _env():
    env = dict(os.environ, QT_QPA_PLATFORM='offscreen')
    env.setdefault('LANG', 'C.UTF-8')
    return env


def _mscore():
    exe = shutil.which('mscore')
    if not exe:
        raise ErroConversao('MuseScore (mscore) não encontrado. Instale o MuseScore 4.')
    return exe


def converter(origem, destino, log=None, timeout=300):
    """origem/destino por extensão: .musicxml → .mscz, .mscz → .pdf/.png/.musicxml."""
    destino = Path(destino)
    destino.unlink(missing_ok=True)  # destino é sempre um arquivo da pasta de trabalho
    rodar([_mscore(), '-o', destino, origem], timeout=timeout, env=_env(), log=log, nome='MuseScore')
    if not destino.exists():
        raise ErroConversao(f'O MuseScore não conseguiu gerar {destino.suffix}.')
    return destino

"""Coloca os arquivos finais na pasta de saída SEM NUNCA SOBRESCREVER.

Um .mscz já existente pode ter sido editado no MuseScore. Se o nome estiver ocupado, grava "Nome (2)".
Substituir só por pedido explícito, e o arquivo antigo vai para a Lixeira.
"""
import os
import re
import shutil
import subprocess
import uuid
from pathlib import Path

from .erros import ErroConversao

_PROIBIDOS = re.compile(r'[/\\:*?"<>|\x00-\x1f]')


def nome_seguro(texto, padrao='Partitura'):
    """Nome de arquivo válido também em pendrive (FAT): mantém acentos e espaços, tira caracteres proibidos."""
    nome = _PROIBIDOS.sub(' ', str(texto or '')).strip().strip('.')
    nome = re.sub(r'\s+', ' ', nome)[:120].strip()
    return nome or padrao


def nome_livre(pasta, base, extensoes):
    """Primeiro nome 'base', 'base (2)', ... sem nenhum arquivo existente com as extensões dadas."""
    pasta = Path(pasta)
    for n in range(1, 1000):
        candidato = base if n == 1 else f'{base} ({n})'
        if not any((pasta / f'{candidato}{ext}').exists() for ext in extensoes):
            return candidato
    raise ErroConversao(f'Há versões demais de "{base}" em {pasta}.')


def copiar_exclusivo(origem, destino):
    """Copia; falha com FileExistsError se o destino já existir (sem janela para sobrescrever)."""
    destino = Path(destino)
    tmp = destino.with_name(f'.{destino.name}.{uuid.uuid4().hex[:8]}.parcial')
    shutil.copyfile(origem, tmp)
    try:
        try:
            os.link(tmp, destino)               # atômico e exclusivo
        except FileExistsError:
            raise
        except OSError:                          # sistemas de arquivos sem links (FAT, exFAT)
            with open(destino, 'xb') as f, open(tmp, 'rb') as g:
                shutil.copyfileobj(g, f)
    finally:
        tmp.unlink(missing_ok=True)


def para_lixeira(caminho):
    r = subprocess.run(['gio', 'trash', str(caminho)], capture_output=True, text=True)
    if r.returncode != 0:
        raise ErroConversao(f'Não consegui mandar "{Path(caminho).name}" para a Lixeira: {r.stderr.strip()}')


def publicar(arquivos, pasta, base, substituir=False):
    """arquivos: {'.mscz': origem, '.pdf': origem}. Todos recebem o mesmo nome-base livre. Devolve {ext: destino}."""
    pasta = Path(pasta)
    pasta.mkdir(parents=True, exist_ok=True)
    base = nome_seguro(base)
    extensoes = list(arquivos)
    if substituir:
        for ext in extensoes:
            alvo = pasta / f'{base}{ext}'
            if alvo.exists():
                para_lixeira(alvo)
    for _ in range(3):  # se outro processo criar o mesmo nome no meio do caminho, tenta o próximo
        nome = nome_livre(pasta, base, extensoes)
        feitos = {}
        try:
            for ext, origem in arquivos.items():
                destino = pasta / f'{nome}{ext}'
                copiar_exclusivo(origem, destino)
                feitos[ext] = destino
            return feitos
        except FileExistsError:
            for criado in feitos.values():
                criado.unlink(missing_ok=True)
    raise ErroConversao(f'Não consegui um nome livre para "{base}" em {pasta}.')

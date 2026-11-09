"""Onde ficam as coisas. Tudo dentro da pasta do programa (a raiz pode ser trocada para testes)."""
import os
from pathlib import Path

CONVERSOR = Path(__file__).resolve().parent.parent            # <pasta do programa>/conversor
RAIZ = Path(os.environ.get('CENTRAL_PARTITURAS_RAIZ') or CONVERSOR.parent).resolve()

ESTADO = RAIZ / '.estado'           # trava do servidor, perfil do navegador, dados do Audiveris, trabalho
MUSICAS = RAIZ / 'musicas'          # uma pasta por música
ENTRADA = RAIZ / 'entrada'          # caixa de entrada: fotos ainda sem música
PARTITURAS = RAIZ / 'partituras'    # saída padrão (.mscz/.pdf)
EXPORTADOS = RAIZ / 'exportados'    # pacotes .zip

AUDIVERIS = CONVERSOR / 'audiveris' / 'opt' / 'audiveris' / 'bin' / 'Audiveris'
TESSDATA = CONVERSOR / 'tessdata'

# Modo de áudio: ambiente próprio (Python 3.12 com torch), modelos baixados pelo instalar.sh --audio
VENV_AUDIO = CONVERSOR / '.venv-audio'
PY_AUDIO = Path(os.environ.get('CENTRAL_PY_AUDIO') or VENV_AUDIO / 'bin' / 'python')
MODELOS_AUDIO = CONVERSOR / 'modelos-audio'
ESTADO_AUDIO = ESTADO / 'audio'     # caches do torch/matplotlib e o último tamanho de trecho que coube na GPU
TEMPORARIOS = ESTADO / 'tmp'        # arquivos temporários grandes (envios de áudio), em disco


def pasta_trabalho(nome):
    """Pasta temporária em disco (não em /tmp, que no Fedora ocupa memória)."""
    pasta = ESTADO / 'trabalho' / nome
    pasta.mkdir(parents=True, exist_ok=True)
    return pasta

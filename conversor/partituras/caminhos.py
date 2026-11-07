"""Onde ficam as coisas. Tudo dentro de image-to-music/ (a raiz pode ser trocada para testes)."""
import os
from pathlib import Path

CONVERSOR = Path(__file__).resolve().parent.parent            # image-to-music/conversor
RAIZ = Path(os.environ.get('CENTRAL_PARTITURAS_RAIZ') or CONVERSOR.parent).resolve()

ESTADO = RAIZ / '.estado'           # trava do servidor, perfil do navegador, dados do Audiveris, trabalho
MUSICAS = RAIZ / 'musicas'          # uma pasta por música
ENTRADA = RAIZ / 'entrada'          # caixa de entrada: fotos ainda sem música
PARTITURAS = RAIZ / 'partituras'    # saída padrão (.mscz/.pdf)
EXPORTADOS = RAIZ / 'exportados'    # pacotes .zip

AUDIVERIS = CONVERSOR / 'audiveris' / 'opt' / 'audiveris' / 'bin' / 'Audiveris'
TESSDATA = CONVERSOR / 'tessdata'


def pasta_trabalho(nome):
    """Pasta temporária em disco (não em /tmp, que no Fedora ocupa memória)."""
    pasta = ESTADO / 'trabalho' / nome
    pasta.mkdir(parents=True, exist_ok=True)
    return pasta

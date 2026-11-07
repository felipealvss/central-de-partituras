"""Utilidades dos testes: dados de referência reais e MusicXML mínimo."""
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

DADOS = Path(__file__).resolve().parent / 'dados'


def dado(nome):
    """Arquivo de referência em testes/dados/. São leituras reais de uma partitura protegida por direitos
    autorais e por isso não vão para o repositório: sem o arquivo, o teste é pulado."""
    p = DADOS / nome
    if not p.exists():
        raise unittest.SkipTest(f'sem o dado de referência testes/dados/{nome} (fica fora do repositório)')
    return p


def homr_unido():
    from partituras import musicxml as mx
    return mx.unir_paginas([mx.ler(dado('homr-pagina1.musicxml')), mx.ler(dado('homr-pagina2.musicxml'))])


def assinatura(m):
    """(figura, alturas) de cada acorde com notas de um compasso — para comparar resultados."""
    acordes, atual = [], None
    for n in m.findall('note'):
        if n.find('chord') is None:
            atual = [(n.findtext('type') or '') + ('.' if n.find('dot') is not None else ''), set()]
            acordes.append(atual)
        if n.find('rest') is None:
            p = n.find('pitch')
            atual[1].add(p.findtext('step') + str(int(float(p.findtext('alter') or 0))) + p.findtext('octave'))
    return [(a[0], tuple(sorted(a[1]))) for a in acordes if a[1]]


def partitura(*compassos, divisoes=2, fifths=0):
    """MusicXML mínimo. Cada compasso: lista de (passo+oitava | 'r' | 'R', duração) ou dict com 'notas' e 'extra'.
    'R' = pausa de compasso inteiro. Ex.: partitura([('C4', 8)], [('R', 8)], [('E4', 8)])."""
    corpo = []
    for i, c in enumerate(compassos, 1):
        extra = ''
        if isinstance(c, dict):
            extra, c = c.get('extra', ''), c['notas']
        attrs = (f'<attributes><divisions>{divisoes}</divisions><key><fifths>{fifths}</fifths></key>'
                 '<time><beats>4</beats><beat-type>4</beat-type></time><clef><sign>F</sign><line>4</line></clef></attributes>'
                 if i == 1 else '')
        notas = ''
        for tok, dur in c:
            if tok in ('r', 'R'):
                notas += f'<note><rest{" measure=\"yes\"" if tok == "R" else ""}/><duration>{dur}</duration><voice>1</voice></note>'
            else:
                notas += (f'<note><pitch><step>{tok[0]}</step><octave>{tok[1]}</octave></pitch>'
                          f'<duration>{dur}</duration><voice>1</voice><type>whole</type></note>')
        corpo.append(f'<measure number="{i}">{attrs}{extra}{notas}</measure>')
    xml = ('<score-partwise version="4.0"><part-list><score-part id="P1"><part-name>X</part-name></score-part></part-list>'
           f'<part id="P1">{"".join(corpo)}</part></score-partwise>')
    return ET.ElementTree(ET.fromstring(xml))


def temporaria(caso):
    """Pasta temporária apagada ao fim do teste."""
    import shutil
    import tempfile
    p = Path(tempfile.mkdtemp(prefix='central-teste-'))
    caso.addCleanup(shutil.rmtree, p, True)
    return p

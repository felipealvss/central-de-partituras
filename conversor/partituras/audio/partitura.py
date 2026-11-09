"""Partitura da linha transcrita, escrita para o instrumento escolhido: compasso e anacruse, tom estimado em som
real, transposição, grafia dos acidentes pela armadura, clave e som do MuseScore explícitos e avisos de extensão.
Só roda no ambiente de áudio (music21)."""
import math
import xml.etree.ElementTree as ET

ACIDENTES_ESTRANHOS = ('E#', 'B#', 'F-', 'C-')


def grafar(score):
    """Acidentes coerentes com a armadura (sustenidos em tom de sustenido, bemóis em tom de bemol) e armadura com
    mais de 6 acidentes trocada pela enarmônica (Dó♯ maior → Ré♭ maior), como um arranjador escreveria."""
    from music21.stream import makeNotation
    armaduras = list(score.recurse().getElementsByClass('KeySignature'))
    for ks in armaduras:
        if ks.sharps > 6:
            ks.sharps -= 12
        elif ks.sharps < -6:
            ks.sharps += 12
    direcao = armaduras[0].sharps if armaduras else 0
    escala = {p.name for p in armaduras[0].asKey('major').pitches} if armaduras else set()
    for n in score.recurse().notes:
        for pt in n.pitches:
            alt = pt.accidental.alter if pt.accidental else 0
            estranho = pt.name in ACIDENTES_ESTRANHOS and pt.name not in escala
            if (direcao >= 0 and alt < 0) or (direcao < 0 and alt > 0) or abs(alt) > 1 or estranho:
                pt.getEnharmonic(inPlace=True)
    for parte in score.parts:  # recalcula quais acidentes aparecem, agora pela armadura certa
        makeNotation.makeAccidentalsInMeasureStream(parte, overrideStatus=True)
    return score


def inicio_dos_compassos(notas, compasso, primeira_barra):
    """Batida em que começa o compasso 1. Notas antes do 1º tempo forte detectado viram anacruse/compassos
    anteriores (o piloto as descartava)."""
    inicio = primeira_barra
    if notas:
        menor = min(n['b0'] for n in notas)
        if menor < inicio:
            inicio -= compasso * math.ceil((inicio - menor) / compasso)
    return inicio


def escrever(notas, instrumento, compasso, bpm, inicio, titulo, compositor, destino_som, destino_escrito):
    """Grava a partitura em som real e a escrita para o instrumento. Devolve tom (som e escrito), número de
    compassos e as notas fora da extensão escrita normal (com o compasso), para os avisos."""
    from music21 import clef, instrument as m21inst, key, metadata, meter, note, stream, tempo
    p = stream.Part()
    inst = getattr(m21inst, instrumento['music21'])()
    inst.instrumentSound = instrumento['som']
    inst.partName = instrumento['nome']
    p.insert(0, inst)
    sinal, linha = instrumento['clave']
    p.insert(0, clef.BassClef() if sinal == 'F' else clef.TrebleClef())
    p.insert(0, meter.TimeSignature(f'{compasso}/4'))
    p.insert(0, tempo.MetronomeMark(number=round(bpm)))
    for n in notas:
        ql = n['b1'] - n['b0']
        if ql > 0:
            p.insert(n['b0'] - inicio, note.Note(midi=int(n['nota']), quarterLength=ql))
    tom = p.analyze('key') if len(p.recurse().notes) > 4 else key.Key('C')
    p.insert(0, key.KeySignature(tom.sharps))
    p.makeRests(fillGaps=True, inPlace=True)
    medidas = p.makeMeasures()
    medidas.makeTies(inPlace=True)
    s = stream.Score()
    s.metadata = metadata.Metadata(title=titulo, composer=compositor or '')
    s.insert(0, medidas)
    s.atSoundingPitch = True
    grafar(s).write('musicxml', fp=str(destino_som))
    escrita = grafar(s.toWrittenPitch(inPlace=False))
    escrita.write('musicxml', fp=str(destino_escrito))
    for arq in (destino_som, destino_escrito):
        _garantir_instrumento(arq, instrumento)
    baixo, alto = instrumento['extensao_escrita']
    fora = []
    for m in escrita.parts[0].getElementsByClass('Measure'):
        for n in m.notes:
            if n.pitch.midi < baixo or n.pitch.midi > alto:
                fora.append({'compasso': int(m.number), 'nota': n.pitch.nameWithOctave.replace('-', 'b'),
                             'acima': n.pitch.midi > alto})
    ks = escrita.recurse().getElementsByClass('KeySignature').first()
    return {'tom_som': _nome_tom(tom), 'tom_escrito': _nome_tom(ks.asKey(tom.mode)) if ks else None,
            'compassos': len(medidas.getElementsByClass('Measure')), 'fora_extensao': fora}


SOLFEJO = {'C': 'Dó', 'D': 'Ré', 'E': 'Mi', 'F': 'Fá', 'G': 'Sol', 'A': 'Lá', 'B': 'Si'}


def _nome_tom(k):
    t = k.tonic.name
    nome = SOLFEJO[t[0]] + t[1:].replace('-', '♭').replace('#', '♯')
    return f"{nome} {'maior' if k.mode == 'major' else 'menor'}"


def _garantir_instrumento(arquivo, instrumento):
    """O MuseScore escolhe som e transposição pelo <instrument-sound> do MusicXML; garante que ele exista (o
    music21 nem sempre o escreve) e que o nome da parte seja o do instrumento escolhido."""
    arvore = ET.parse(arquivo)
    raiz = arvore.getroot()
    for sp in raiz.iter('score-part'):
        nome = sp.find('part-name')
        if nome is not None:
            nome.text = instrumento['nome']
        si = sp.find('score-instrument')
        if si is None:
            si = ET.SubElement(sp, 'score-instrument', id=f"{sp.get('id')}-I1")
            ET.SubElement(si, 'instrument-name').text = instrumento['nome']
        if si.find('instrument-sound') is None:
            som = ET.Element('instrument-sound')
            som.text = instrumento['som']
            pos = next((i for i, el in enumerate(si) if el.tag not in ('instrument-name', 'instrument-abbreviation')),
                       len(si))
            si.insert(pos, som)
    arvore.write(arquivo, encoding='UTF-8', xml_declaration=True)

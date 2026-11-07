"""Notação compacta → MusicXML: o formato das transcrições assistidas (revisão com o Claude).

Uma transcrição é um arquivo Python curto, só com os dados da música:

    from partituras.notacao import Partitura
    p = Partitura('Título', compositor='...', parte='Trombone 3 / Tuba', instrumento='Tuba', midi=59)
    p.pausas(1, 11, arm=4, tempo=('Hushed', 96), sistema=True)
    p.c(12, ('B1 B2', 'w', {'lig': 'ini'}), din='p')

Evento: (notas, duração, opções). Notas da mais grave para a mais aguda, em notação inglesa com oitava
(C4 = Dó central); letra sem acidente segue a armadura vigente; 'n' força bequadro; '#'/'b' forçam a
alteração; 'r' = pausa. Durações: w, h., h, q., q, e., e, s (s = semicolcheia; exige divisoes=4).
Opções do evento: lig ('ini'|'meio'|'fim'), art (['accent', 'staccato', 'strong-accent', 'tenuto']),
texto ('rit.'), fermata, inteira (pausa de compasso inteiro).
Opções do compasso: arm (armadura em quintas: 4 = Mi maior, -5 = Ré♭ maior), tempo=(texto, bpm),
din ('p', 'mf', 'mfp'...), forquilha=[('cresc'|'dim', índice do evento)], forquilha_fim, barra
('dupla'|'final'), sistema, pagina; em pausas(): barra_ult (barra no último compasso do grupo).

Gerar: .venv/bin/python -m partituras.notacao transcricao.py -o saida.musicxml [--mscz saida.mscz] [--pdf]
"""
import argparse
import re
import runpy
from pathlib import Path
from xml.sax.saxutils import escape

DURACOES = {'w': (4, 'whole', 0), 'h.': (3, 'half', 1), 'h': (2, 'half', 0), 'q.': (1.5, 'quarter', 1),
            'q': (1, 'quarter', 0), 'e.': (0.75, 'eighth', 1), 'e': (0.5, 'eighth', 0), 's': (0.25, '16th', 0)}
SUSTENIDOS, BEMOIS = 'FCGDAEB', 'BEADGCF'
DINAMICAS = {'ppp', 'pp', 'p', 'mp', 'mf', 'f', 'ff', 'fff', 'fp', 'sf', 'sfz', 'fz', 'sfp', 'rf', 'rfz'}


class Partitura:
    def __init__(self, titulo, compositor='', direitos='', parte='', abreviacao='', instrumento='', midi=1,
                 clave=('F', 4), compasso=(4, 4), divisoes=2):
        self.titulo, self.compositor, self.direitos = titulo, compositor, direitos
        self.parte, self.abreviacao, self.instrumento, self.midi = parte, abreviacao, instrumento, midi
        self.clave, self.compasso, self.divisoes = clave, compasso, divisoes
        self.M = {}

    # ------------------------------------------------ entrada de dados
    def c(self, n, *eventos, **extras):
        self.M[n] = (list(eventos), extras)

    def pausas(self, ini, qtd, **extras):
        for k in range(qtd):
            self.c(ini + k, ('r', 'w', {'inteira': True}), **(dict(extras, multirest=qtd) if k == 0 else {}))

    # ------------------------------------------------ geração
    def _duracao(self, simbolo):
        quartos, tipo, ponto = DURACOES[simbolo]
        dur = quartos * self.divisoes
        if dur != int(dur):
            raise ValueError(f'A duração "{simbolo}" exige mais divisões (use divisoes=4).')
        return int(dur), tipo, ponto

    @staticmethod
    def _alteracao(letra, arm):
        if arm > 0:
            return 1 if letra in SUSTENIDOS[:arm] else 0
        if arm < 0:
            return -1 if letra in BEMOIS[:-arm] else 0
        return 0

    def _nota(self, tok, arm, dur, tipo, ponto, primeira, opc):
        m = re.fullmatch(r'([A-G])(n|#|b)?(\d)', tok)
        if not m:
            raise ValueError(f'Nota inválida: {tok}')
        letra, acc, oit = m.groups()
        alt = {'n': 0, '#': 1, 'b': -1}.get(acc)
        if alt is None:
            alt = self._alteracao(letra, arm)
        x = '<note>' + ('' if primeira else '<chord/>')
        x += f'<pitch><step>{letra}</step>' + (f'<alter>{alt}</alter>' if alt else '') + f'<octave>{oit}</octave></pitch><duration>{dur}</duration>'
        tipos = {'ini': ['start'], 'fim': ['stop'], 'meio': ['stop', 'start']}.get(opc.get('lig'), [])
        x += ''.join(f'<tie type="{t}"/>' for t in tipos)
        x += f'<voice>1</voice><type>{tipo}</type>' + ('<dot/>' if ponto else '')
        notac = ''.join(f'<tied type="{t}"/>' for t in tipos)
        if primeira and opc.get('art'):
            notac += '<articulations>' + ''.join(f'<{a}/>' if a != 'strong-accent' else '<strong-accent type="up"/>'
                                                  for a in opc['art']) + '</articulations>'
        if notac:
            x += f'<notations>{notac}</notations>'
        return x + '</note>'

    @staticmethod
    def _direcao(conteudo, lugar='above'):
        return f'<direction placement="{lugar}"><direction-type>{conteudo}</direction-type></direction>'

    @staticmethod
    def _tempo(texto, bpm):
        partes = f'<direction-type><words font-weight="bold">{escape(texto)}</words></direction-type>' if texto else ''
        partes += (f'<direction-type><metronome parentheses="yes"><beat-unit>quarter</beat-unit>'
                   f'<per-minute>{bpm}</per-minute></metronome></direction-type>')
        return f'<direction placement="above">{partes}<sound tempo="{bpm}"/></direction>'

    def musicxml(self):
        total = max(self.M)
        faltam = sorted(set(range(1, total + 1)) - set(self.M))
        if faltam:
            raise ValueError(f'Faltam compassos: {faltam[:20]}')
        M = {n: (ev, dict(ex)) for n, (ev, ex) in self.M.items()}
        for n in list(M):  # barra no último compasso de cada grupo de pausas
            ev, ex = M[n]
            if ex.get('barra_ult'):
                M[n + ex['multirest'] - 1][1]['barra'] = ex['barra_ult']
        beats, beat_type = self.compasso
        esperado = beats * self.divisoes * 4 // beat_type
        corpo, arm, erros = [], 0, []
        for n in range(1, total + 1):
            ev, ex = M[n]
            x = f'<measure number="{n}">'
            if ex.get('pagina'):
                x += '<print new-page="yes"/>'
            elif ex.get('sistema') and n > 1:
                x += '<print new-system="yes"/>'
            attrs = f'<divisions>{self.divisoes}</divisions>' if n == 1 else ''
            if 'arm' in ex:
                arm = ex['arm']
                attrs += f'<key><fifths>{arm}</fifths><mode>major</mode></key>'
            if n == 1:
                attrs += (f'<time><beats>{beats}</beats><beat-type>{beat_type}</beat-type></time>'
                          f'<clef><sign>{self.clave[0]}</sign><line>{self.clave[1]}</line></clef>')
            if ex.get('multirest'):
                attrs += f'<measure-style><multiple-rest>{ex["multirest"]}</multiple-rest></measure-style>'
            if attrs:
                x += f'<attributes>{attrs}</attributes>'
            if ex.get('tempo'):
                x += self._tempo(*ex['tempo'])
            if ex.get('din'):
                d = ex['din']
                x += self._direcao(f'<dynamics><{d}/></dynamics>' if d in DINAMICAS
                                   else f'<dynamics><other-dynamics>{escape(d)}</other-dynamics></dynamics>', 'below')
            soma = 0
            forq = {pos: tipo for tipo, pos in ex.get('forquilha', [])}
            for i, (notas, simbolo, opc) in enumerate(ev):
                if i in forq:
                    x += self._direcao(f'<wedge type="{"crescendo" if forq[i] == "cresc" else "diminuendo"}"/>', 'below')
                if opc.get('texto'):
                    x += self._direcao(f'<words font-style="italic">{escape(opc["texto"])}</words>')
                dur, tipo, ponto = self._duracao(simbolo)
                if opc.get('inteira'):
                    dur = esperado
                soma += dur
                if notas == 'r':
                    fer = '<notations><fermata type="upright"/></notations>' if opc.get('fermata') else ''
                    x += (f'<note><rest{" measure=\"yes\"" if opc.get("inteira") else ""}/><duration>{dur}</duration><voice>1</voice>'
                          + ('' if opc.get('inteira') else f'<type>{tipo}</type>' + ('<dot/>' if ponto else '')) + f'{fer}</note>')
                else:
                    for j, tok in enumerate(notas.split()):
                        x += self._nota(tok, arm, dur, tipo, ponto, j == 0, opc)
            if ex.get('forquilha_fim'):
                x += self._direcao('<wedge type="stop"/>', 'below')
            if soma != esperado:
                erros.append(f'compasso {n}: {soma / self.divisoes:g} de {beats} tempos')
            b = ex.get('barra')
            if b:
                x += f'<barline location="right"><bar-style>{"light-light" if b == "dupla" else "light-heavy"}</bar-style></barline>'
            corpo.append(x + '</measure>')
        if erros:
            raise ValueError('Compassos com duração errada: ' + '; '.join(erros))
        return f'''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE score-partwise PUBLIC "-//Recordare//DTD MusicXML 4.0 Partwise//EN" "http://www.musicxml.org/dtds/partwise.dtd">
<score-partwise version="4.0">
<work><work-title>{escape(self.titulo)}</work-title></work>
<identification><creator type="composer">{escape(self.compositor)}</creator>
<rights>{escape(self.direitos)}</rights></identification>
<part-list><score-part id="P1"><part-name>{escape(self.parte)}</part-name><part-abbreviation>{escape(self.abreviacao)}</part-abbreviation>
<score-instrument id="P1-I1"><instrument-name>{escape(self.instrumento)}</instrument-name></score-instrument>
<midi-instrument id="P1-I1"><midi-program>{self.midi}</midi-program></midi-instrument></score-part></part-list>
<part id="P1">{''.join(corpo)}</part></score-partwise>'''

    def salvar(self, caminho):
        Path(caminho).write_text(self.musicxml(), encoding='utf-8')
        return Path(caminho)


def carregar_transcricao(arquivo):
    """Executa o arquivo de transcrição e devolve a Partitura definida nele."""
    ns = runpy.run_path(str(arquivo))
    for valor in ns.values():
        if type(valor).__name__ == 'Partitura' and hasattr(valor, 'musicxml'):
            return valor
    raise ValueError(f'{arquivo} não define nenhuma Partitura.')


def main():
    ap = argparse.ArgumentParser(description='Gera MusicXML (e opcionalmente .mscz/.pdf) de uma transcrição em notação compacta.')
    ap.add_argument('transcricao')
    ap.add_argument('-o', '--musicxml', required=True)
    ap.add_argument('--mscz')
    ap.add_argument('--pdf', action='store_true')
    args = ap.parse_args()
    p = carregar_transcricao(args.transcricao)
    xml = p.salvar(args.musicxml)
    print(f'MusicXML: {xml} ({max(p.M)} compassos, todos com a duração certa)')
    if args.mscz:
        import tempfile
        from . import musescore
        from .publicar import publicar
        destino = Path(args.mscz)
        with tempfile.TemporaryDirectory() as tmp:
            arquivos = {'.mscz': musescore.converter(xml, Path(tmp) / 'p.mscz')}
            if args.pdf:
                arquivos['.pdf'] = musescore.converter(arquivos['.mscz'], Path(tmp) / 'p.pdf')
            for ext, final in publicar(arquivos, destino.parent, destino.stem).items():
                print(f'{ext[1:].upper()}: {final}')  # nunca sobrescreve: se existir, salva como "Nome (2)"


if __name__ == '__main__':
    main()

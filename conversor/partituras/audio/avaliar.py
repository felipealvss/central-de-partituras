"""Mede uma transcrição contra um gabarito (a parte corrigida à mão no MuseScore). Ambiente de áudio.

    python -m partituras.audio.avaliar GABARITO TRANSCRICAO [--json SAIDA] [--janela 4]

GABARITO e TRANSCRICAO: .mscz (convertido pelo MuseScore), .musicxml/.mxl ou a pasta de uma versão da Central
(usa a partitura.musicxml dela). As duas partes vão para som real e as notas ligadas viram uma nota só: as
ligaduras da escrita (nota que atravessa a barra) não contam como erro; contam as musicais:

- ligadura indevida: a transcrição tem uma nota só onde o gabarito ataca de novo a mesma nota;
- ligadura faltante: a transcrição ataca de novo onde o gabarito sustenta a nota.

As frases (notas separadas por pausas de pelo menos um compasso de 4/4) são alinhadas uma a uma, com
deslocamento de até --janela tempos, porque o gabarito pode ter um compasso a mais ou a menos no começo
(anacruse) que a transcrição. As medidas são em tempos (semínimas), com tolerância de 1/8 de tempo:
F1 de ataque+altura e de ataque+altura+fim (mir_eval). Medem o trabalho de correção, não um acerto absoluto.
"""
import argparse
import json
import sys
import tempfile
from pathlib import Path

import numpy as np

TOLERANCIA = 0.125   # tempos (1/8 de tempo, metade de uma semicolcheia)
PAUSA_FRASE = 4.0    # tempos de silêncio que separam frases
PASSO = 0.25         # deslocamentos testados no alinhamento: de semicolcheia em semicolcheia


def _musicxml(caminho, tmp):
    caminho = Path(caminho)
    if caminho.is_dir():
        caminho = caminho / 'partitura.musicxml'
    if caminho.suffix.lower() == '.mscz':
        from .. import musescore
        destino = Path(tmp) / f'{caminho.stem}.musicxml'
        musescore.converter(caminho, destino)
        return destino
    return caminho


def notas_da_partitura(caminho):
    """[{'ini', 'fim', 'nota'}] em tempos desde o começo, som real, notas ligadas juntas (só a 1ª parte)."""
    import music21
    s = music21.converter.parse(str(caminho))
    parte = s.parts[0] if s.parts else s
    if not parte.atSoundingPitch:
        parte = parte.toSoundingPitch()
    notas = []
    for n in parte.flatten().notes:
        if n.duration.isGrace or n.quarterLength <= 0:
            continue
        p = max(n.pitches, key=lambda x: x.midi)
        ini, fim = float(n.offset), float(n.offset + n.quarterLength)
        liga = n.tie is not None and n.tie.type in ('stop', 'continue')
        if liga and notas and notas[-1]['nota'] == p.midi and abs(notas[-1]['fim'] - ini) < 1e-6:
            notas[-1]['fim'] = fim
        else:
            notas.append({'ini': ini, 'fim': fim, 'nota': int(round(p.midi))})
    return notas


def frases(notas, pausa=PAUSA_FRASE):
    grupos = []
    for n in notas:
        if grupos and n['ini'] - grupos[-1][-1]['fim'] < pausa:
            grupos[-1].append(n)
        else:
            grupos.append([n])
    return grupos


def _acertos(ref, est, desloc, tol=TOLERANCIA):
    """Ataques+altura que batem com a transcrição deslocada de `desloc` tempos (casamento guloso, 1 para 1)."""
    usados, n = set(), 0
    for r in ref:
        for i, e in enumerate(est):
            if i not in usados and e['nota'] == r['nota'] and abs(e['ini'] + desloc - r['ini']) <= tol:
                usados.add(i)
                n += 1
                break
    return n


def _deslocar(notas, d):
    return [{**n, 'ini': n['ini'] + d, 'fim': n['fim'] + d} for n in notas]


def _metricas(ref, est, tol=TOLERANCIA):
    from mir_eval.transcription import precision_recall_f1_overlap
    if not ref or not est:
        return {'precisao': 0.0, 'revocacao': 0.0, 'f1_ataque_altura': 0.0, 'f1_ataque_fim': 0.0}
    hz = lambda ns: 440.0 * 2 ** ((np.array([n['nota'] for n in ns], dtype=float) - 69) / 12)
    iv = lambda ns: np.array([[n['ini'], max(n['fim'], n['ini'] + 1e-3)] for n in ns])
    p, r, f, _ = precision_recall_f1_overlap(iv(ref), hz(ref), iv(est), hz(est), onset_tolerance=tol,
                                             pitch_tolerance=50.0, offset_ratio=None)
    _, _, f2, _ = precision_recall_f1_overlap(iv(ref), hz(ref), iv(est), hz(est), onset_tolerance=tol,
                                              pitch_tolerance=50.0, offset_ratio=0.2, offset_min_tolerance=tol)
    return {'precisao': round(p, 4), 'revocacao': round(r, 4), 'f1_ataque_altura': round(f, 4),
            'f1_ataque_fim': round(f2, 4)}


def ligaduras(ref, est, tol=TOLERANCIA):
    """(indevidas, faltantes) depois do alinhamento; ver o docstring do módulo."""
    def dentro(longas, ataques):
        total = 0
        for a in longas:
            total += sum(1 for b in ataques if b['nota'] == a['nota'] and a['ini'] + tol < b['ini'] < a['fim'] - tol)
        return total
    return dentro(est, ref), dentro(ref, est)


def _passos(limite):
    return [round(k * PASSO, 4) for k in range(-int(limite / PASSO), int(limite / PASSO) + 1)]


def _melhor(ref, est, candidatos, tol, preferido=0.0):
    """O deslocamento com mais acertos; no empate, o mais perto do preferido."""
    return max(candidatos, key=lambda d: (_acertos(ref, est, d, tol), -abs(d - preferido)))


def avaliar(ref, est, janela=4.0, tol=TOLERANCIA, pausa=PAUSA_FRASE):
    """Compara notas do gabarito (ref) e da transcrição (est); devolve as medidas gerais e por frase.

    Um deslocamento geral (até `janela` tempos) e, em cada frase do gabarito, o melhor deslocamento até `janela`
    tempos em volta dele. As notas da transcrição que não caem em frase nenhuma contam como notas a mais."""
    geral = _melhor(ref, est, _passos(janela), tol)
    usados, alinhadas, por_frase = set(), [], []
    for f in frases(ref, pausa):
        ini, fim = f[0]['ini'], f[-1]['fim']
        perto = [i for i, e in enumerate(est)
                 if i not in usados and ini - 2 * janela - tol <= e['ini'] + geral <= fim + 2 * janela + tol]
        desloc = _melhor(f, [est[i] for i in perto], [geral + c for c in _passos(janela)], tol, preferido=geral)
        dentro = [i for i in perto if ini - pausa / 2 <= est[i]['ini'] + desloc <= fim + pausa / 2]
        usados.update(dentro)
        e_frase = _deslocar([est[i] for i in dentro], desloc)
        alinhadas.extend(e_frase)
        ind, falt = ligaduras(f, e_frase, tol)
        por_frase.append({'inicio': ini, 'fim': fim, 'notas_gabarito': len(f), 'notas_transcricao': len(e_frase),
                          'deslocamento': desloc, **_metricas(f, e_frase, tol),
                          'ligaduras_indevidas': ind, 'ligaduras_faltantes': falt})
    sobras = [est[i] for i in range(len(est)) if i not in usados]
    alinhadas.extend(_deslocar(sobras, geral))
    alinhadas.sort(key=lambda n: n['ini'])
    ind, falt = ligaduras(ref, alinhadas, tol)
    return {**_metricas(ref, alinhadas, tol), 'notas_gabarito': len(ref), 'notas_transcricao': len(est),
            'notas_fora_das_frases': len(sobras), 'ligaduras_indevidas': ind, 'ligaduras_faltantes': falt,
            'deslocamento_geral': geral, 'tolerancia_tempos': tol, 'frases': por_frase}


def texto(res):
    linhas = [f"F1 ataque+altura: {res['f1_ataque_altura']:.3f} (precisão {res['precisao']:.3f}, "
              f"revocação {res['revocacao']:.3f}) · F1 com o fim: {res['f1_ataque_fim']:.3f}",
              f"Notas: {res['notas_gabarito']} no gabarito, {res['notas_transcricao']} na transcrição "
              f"({res['notas_fora_das_frases']} fora das frases do gabarito)",
              f"Ligaduras: {res['ligaduras_indevidas']} indevidas, {res['ligaduras_faltantes']} faltantes · "
              f"deslocamento geral {res['deslocamento_geral']:+g} tempos"]
    for i, f in enumerate(res['frases'], 1):
        linhas.append(f"  frase {i:2d} (tempo {f['inicio']:g}): F1 {f['f1_ataque_altura']:.3f} · "
                      f"{f['notas_gabarito']}/{f['notas_transcricao']} notas · desloc. {f['deslocamento']:+g} · "
                      f"ligaduras {f['ligaduras_indevidas']}+/{f['ligaduras_faltantes']}-")
    return '\n'.join(linhas)


def main(args=None):
    p = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    p.add_argument('gabarito')
    p.add_argument('transcricao')
    p.add_argument('--json', type=Path)
    p.add_argument('--janela', type=float, default=4.0)
    a = p.parse_args(args)
    with tempfile.TemporaryDirectory(prefix='central-avaliar-') as tmp:
        ref = notas_da_partitura(_musicxml(a.gabarito, tmp))
        est = notas_da_partitura(_musicxml(a.transcricao, tmp))
    res = avaliar(ref, est, janela=a.janela)
    res = {'gabarito': str(a.gabarito), 'transcricao': str(a.transcricao), **res}
    if a.json:
        a.json.write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding='utf-8')
    print(texto(res))
    return res


if __name__ == '__main__':
    main(sys.argv[1:])

"""Transcrição da linha isolada em duas fases, como no reconhecimento de fotos:

- analisar: trechos, curva de altura (pYIN), notas brutas e batidas (Beat This!) — o mais demorado depois da
  separação; o resultado fica guardado em <conversão>/analise/;
- gerar: grade de compasso com os ajustes da revisão, quantização, partitura para o instrumento, MuseScore e
  conferência (síntese e imagens) — segundos; é o que roda de novo quando o usuário ajusta algo.

Ambiente de áudio.
"""
import json
import math
from pathlib import Path

import numpy as np

from . import conferencia, linha, partitura, ritmo
from . import instrumentos as tabela

ESTILO = Path(__file__).resolve().parent / 'estilo-parte.mss'


def _nada(*_a, **_k):
    pass


def _hz(nome):
    return 440 * 2 ** ((tabela.midi(nome) - 69) / 12)


def analisar(mistura, stem, voz, instrumento_id, pasta, checkpoint_batidas, segmentacao=None, progresso=_nada):
    inst = tabela.obter(instrumento_id)
    segmentacao = segmentacao or tabela.SEGMENTACAO_PADRAO
    seg = tabela.SEGMENTACAO[segmentacao]
    progresso('analisando', f'Procurando onde o {inst["nome"].lower()} toca', None, None)
    mix, y = linha.ler_mono(mistura), linha.ler_mono(stem)
    n = min(len(mix), len(y))
    mix, y = mix[:n], y[:n]
    voz_y = linha.ler_mono(voz)[:n] if voz and Path(voz).exists() else None
    trechos, fora_db = linha.localizar(mix, y, voz_y)
    fmin, fmax = (_hz(x) for x in inst['busca'])
    notas, curvas = [], {}
    for k, t in enumerate(trechos, 1):
        progresso('analisando', f'Lendo as notas do trecho {k} de {len(trechos)}', k, len(trechos))
        i0, i1 = int(max(0, t['inicio'] - 0.15) * linha.SR), int(min(n / linha.SR, t['fim'] + 0.15) * linha.SR)
        ns, tt, midi = linha.notas_do_trecho(y[i0:i1], i0 / linha.SR, fmin, fmax, seg)
        for x in ns:
            x['trecho'] = t['indice']
        notas += ns
        curvas[t['indice']] = (i0, i1, tt, midi)
    desvio = linha.afinacao(notas)
    for x in notas:
        x['nota'] = int(round(x['alt'] - desvio))
    progresso('analisando', 'Achando a pulsação e os tempos fortes', None, None)
    batidas, fortes = ritmo.batidas(mistura, checkpoint_batidas)
    analise = {'formato': 1, 'instrumento': instrumento_id, 'segmentacao': segmentacao, 'amostras': n,
               'trechos': trechos, 'fora_dos_trechos_db': fora_db, 'notas': notas, 'afinacao': desvio,
               'batidas': batidas, 'fortes': fortes, 'presenca': linha.presenca(y)}
    pasta = Path(pasta)
    pasta.mkdir(parents=True, exist_ok=True)
    (pasta / 'analise.json').write_text(json.dumps(analise, ensure_ascii=False), encoding='utf-8')
    arrays = {}
    for k, (i0, i1, tt, midi) in curvas.items():
        arrays[f'janela_{k}'], arrays[f'tt_{k}'], arrays[f'midi_{k}'] = np.array([i0, i1]), tt, midi
    np.savez_compressed(pasta / 'curvas.npz', **arrays)
    return analise


def carregar_analise(pasta):
    pasta = Path(pasta)
    analise = json.loads((pasta / 'analise.json').read_text(encoding='utf-8'))
    dados = np.load(pasta / 'curvas.npz')
    curvas = {t['indice']: (*[int(v) for v in dados[f"janela_{t['indice']}"]], dados[f"tt_{t['indice']}"],
                            dados[f"midi_{t['indice']}"]) for t in analise['trechos']}
    return analise, curvas


def gerar(analise, curvas, stem, pasta, ajustes, titulo, compositor=None, musescore=True, pdf=True,
          progresso=_nada):
    """Gera a versão em `pasta`: partitura.musicxml (escrita para o instrumento), partitura-som-real.musicxml,
    .mscz/.pdf (se musescore), sintese.flac, trecho-NN.png, notas.json, conferencia.json/txt.
    Devolve {'conferencia': rel, 'arquivos': {...}}."""
    import soundfile as sf
    inst = tabela.obter(analise['instrumento'])
    seg = tabela.SEGMENTACAO[analise['segmentacao']]
    aj = tabela.validar_ajustes(ajustes)
    pasta = Path(pasta)
    pasta.mkdir(parents=True, exist_ok=True)
    progresso('partitura', 'Montando a partitura', None, None)
    g = ritmo.grade(analise['batidas'], analise['fortes'], aj)
    incluidas = [n for n in analise['notas'] if aj['trechos'].get(str(n['trecho']), True)]
    q = ritmo.quantizar(incluidas, g['batidas'], aj.get('grade', 4), legato=seg['legato'])
    inicio = partitura.inicio_dos_compassos(q, g['compasso'], g['primeira_barra'])
    info = partitura.escrever(q, inst, g['compasso'], g['bpm'], inicio, titulo, compositor,
                              pasta / 'partitura-som-real.musicxml', pasta / 'partitura.musicxml')

    def compasso_de(t):
        return int(math.floor((ritmo.para_batida(t, g['batidas']) - inicio) / g['compasso'])) + 1

    trechos = []
    for t in analise['trechos']:
        dentro = [n for n in q if n['trecho'] == t['indice']]
        trechos.append({**t, 'compasso_ini': compasso_de(t['inicio']), 'compasso_fim': compasso_de(t['fim']),
                        'notas': len(dentro), 'baixa_confianca': sum(1 for n in dentro if n['conf'] <= 0.5),
                        'incluido': aj['trechos'].get(str(t['indice']), True)})
    rel = conferencia.relatorio(inst, analise, g, aj, q, trechos, info)
    arquivos = {'.musicxml': pasta / 'partitura.musicxml'}
    progresso('conferencia', 'Preparando a conferência (síntese e imagens)', None, None)
    sf.write(pasta / 'sintese.flac', conferencia.sintese(q, analise['amostras'], analise['afinacao']), linha.SR,
             subtype='PCM_16')
    y = linha.ler_mono(stem)[:analise['amostras']]
    for t in trechos:
        i0, i1, tt, midi = curvas[t['indice']]
        conferencia.figura(pasta / f"trecho-{t['indice']:02d}.png", y[i0:i1], i0 / linha.SR, tt, midi,
                           [n for n in q if n['trecho'] == t['indice']], g['batidas'],
                           f"Trecho {t['indice']} · c. {t['compasso_ini']}–{t['compasso_fim']} · {t['notas']} notas")
    (pasta / 'notas.json').write_text(json.dumps(
        [{k: n[k] for k in ('trecho', 'nota', 't0', 't1', 'b0', 'b1', 'conf', 'desvio')} for n in q], indent=0),
        encoding='utf-8')
    (pasta / 'conferencia.json').write_text(json.dumps(rel, ensure_ascii=False, indent=1), encoding='utf-8')
    (pasta / 'conferencia.txt').write_text(conferencia.texto(rel) + '\n', encoding='utf-8')
    arquivos['-conferencia.txt'] = pasta / 'conferencia.txt'
    if musescore:
        from .. import musescore as ms
        progresso('musescore', 'Gerando o arquivo do MuseScore', None, None)
        arquivos['.mscz'] = ms.converter(pasta / 'partitura.musicxml', pasta / 'partitura.mscz',
                                         log=pasta / 'musescore.log', estilo=ESTILO)
        if pdf:
            arquivos['.pdf'] = ms.converter(arquivos['.mscz'], pasta / 'partitura.pdf',
                                            log=pasta / 'musescore-pdf.log')
    return {'conferencia': rel, 'arquivos': arquivos, 'notas': q}

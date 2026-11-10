"""Fase H: mede as regras de segmentação contra um gabarito (ferramenta de desenvolvimento; ambiente de áudio).

    .venv-audio/bin/python ferramentas/experimentar_audio.py GABARITO [--dados DIR] [--saida DIR] [--instrumento ID]

GABARITO: a parte corrigida à mão (.mscz ou .musicxml). DIR de dados: mistura.flac, saxophone.flac (ou o stem do
instrumento) e vocal.flac, como em testes/dados/audio. Transcreve com a segmentação "piloto" (linha de base), com
cada regra da "melhorada" ligada sozinha e com a "melhorada" inteira, mede cada uma contra o gabarito
(partituras.audio.avaliar) e grava a tabela em <saida>/resultados.json. Entra no padrão a regra que sobe o F1 ou
reduz os erros de ligadura sem piorar o resto.
"""
import argparse
import json
import re
import sys
import tempfile
from pathlib import Path

AQUI = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AQUI))
from partituras import caminhos  # noqa: E402
from partituras.audio import avaliar, instrumentos, mega53, transcricao  # noqa: E402


def variantes():
    base, melhor = instrumentos.SEGMENTACAO['piloto'], instrumentos.SEGMENTACAO['melhorada']
    vs = {'piloto': dict(base)}
    for chave, valor in melhor.items():
        if base.get(chave) != valor:
            vs[f'{chave}={valor}'] = {**base, chave: valor}
    vs['melhorada'] = dict(melhor)
    return vs


def main(args=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('gabarito', type=Path)
    p.add_argument('--dados', type=Path, default=AQUI / 'testes' / 'dados' / 'audio')
    p.add_argument('--saida', type=Path)
    p.add_argument('--instrumento', default=instrumentos.PADRAO)
    a = p.parse_args(args)
    inst = instrumentos.obter(a.instrumento)
    saida = a.saida or Path(tempfile.mkdtemp(prefix='central-experimento-'))
    batidas = caminhos.MODELOS_AUDIO / mega53.BEAT_THIS['arquivo']
    with tempfile.TemporaryDirectory(prefix='central-gabarito-') as tmp:
        ref = avaliar.notas_da_partitura(avaliar._musicxml(a.gabarito, tmp))
    print(f'gabarito: {len(ref)} notas · resultados em {saida}', flush=True)
    resultados = []
    for nome, seg in variantes().items():
        chave = f'experimento:{nome}'
        instrumentos.SEGMENTACAO[chave] = seg
        pasta = saida / re.sub(r'[^\w.=-]+', '_', nome)
        stem = a.dados / f"{inst['stem']}.flac"
        transcricao.analisar(a.dados / 'mistura.flac', stem, a.dados / 'vocal.flac', inst['id'], pasta / 'analise',
                             batidas, segmentacao=chave)
        analise, curvas = transcricao.carregar_analise(pasta / 'analise')
        transcricao.gerar(analise, curvas, stem, pasta / 'versao', {}, 'Experimento', musescore=False)
        r = avaliar.avaliar(ref, avaliar.notas_da_partitura(pasta / 'versao' / 'partitura.musicxml'))
        resultados.append({'variante': nome, 'segmentacao': seg, **{k: v for k, v in r.items() if k != 'frases'}})
        print(f"{nome:28s} F1 {r['f1_ataque_altura']:.3f} (P {r['precisao']:.3f} R {r['revocacao']:.3f}) · "
              f"F1 c/ fim {r['f1_ataque_fim']:.3f} · ligaduras {r['ligaduras_indevidas']} indevidas, "
              f"{r['ligaduras_faltantes']} faltantes · {r['notas_transcricao']} notas", flush=True)
    (saida / 'resultados.json').write_text(json.dumps(resultados, ensure_ascii=False, indent=2), encoding='utf-8')
    return resultados


if __name__ == '__main__':
    main()

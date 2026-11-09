"""Executa UM trabalho de áudio da fila, num processo separado e no ambiente de áudio:

    python -m partituras.audio.trabalho tarefa.json

Tipos: 'baixar' (link → audio/original.<ext>), 'converter' (mistura → separação, se o cache da música ainda não
tem os stems → análise → versão) e 'acabar' (só uma nova versão, com os ajustes da revisão). O resultado tem o
mesmo formato do trabalhador de fotos, para a biblioteca registrar a versão do mesmo jeito.

Os eventos (progresso e resultado) saem em linhas JSON por uma cópia própria da saída padrão; tudo o que as
bibliotecas imprimem (avisos, barras de progresso) vai para o log de erros da tarefa.
Importa só a biblioteca padrão no topo: o servidor pode importar este módulo sem torch nem librosa.
"""
import json
import os
import sys
import traceback
from datetime import datetime
from pathlib import Path

from .. import caminhos
from ..erros import ErroConversao

_canal = None


def emitir(**dados):
    print(json.dumps(dados, ensure_ascii=False), file=_canal or sys.stdout, flush=True)


def _isolar_saida():
    global _canal
    sys.stdout.flush()
    _canal = os.fdopen(os.dup(1), 'w', buffering=1, encoding='utf-8')
    os.dup2(2, 1)  # print() e bibliotecas que escrevem no descritor 1 vão para o log


def _ambiente():
    """Caches do torch, matplotlib e CUDA dentro do projeto; alocador da GPU menos fragmentado; prioridade baixa
    (a separação ocupa a máquina por minutos)."""
    for variavel, pasta in (('TORCH_HOME', 'torch'), ('MPLCONFIGDIR', 'matplotlib'), ('CUDA_CACHE_PATH', 'cuda'),
                            ('NUMBA_CACHE_DIR', 'numba')):
        os.environ.setdefault(variavel, str(caminhos.ESTADO_AUDIO / pasta))
    os.environ.setdefault('PYTORCH_CUDA_ALLOC_CONF', 'expandable_segments:True')
    try:
        os.nice(10)
    except OSError:
        pass


def _proxima_versao(conv):
    versoes = Path(conv) / 'versoes'
    versoes.mkdir(parents=True, exist_ok=True)
    n = 1 + max((int(p.name) for p in versoes.iterdir() if p.name.isdigit()), default=0)
    return n, versoes / f'{n:02d}'


def converter(tarefa, progresso):
    from . import decodificar, instrumentos, mega53, separar, transcricao
    from .. import publicar
    pasta_audio = Path(tarefa['pasta_audio'])
    mistura = pasta_audio / 'mistura.flac'
    if not mistura.exists():
        progresso('preparando', 'Decodificando o áudio', None, None)
        decodificar.para_mistura(tarefa['audio']['original'], mistura)
    cache = pasta_audio / 'separacao' / mega53.VERSAO
    if cache.parent.exists():
        separar.limpar_temporarios(cache.parent)
    info_sep = separar.cache_valido(cache, instrumentos.STEMS)
    if info_sep is None:
        info_sep = separar.separar(mistura, cache, caminhos.MODELOS_AUDIO / mega53.CHECKPOINT['arquivo'],
                                   instrumentos.STEMS, arquivo_gpu=caminhos.ESTADO_AUDIO / 'gpu.json',
                                   progresso=progresso)
        info_sep['cache'] = False
    else:
        info_sep = {**info_sep, 'cache': True}
    inst = instrumentos.obter(tarefa['instrumento'])
    stem = cache / f"{inst['stem']}.flac"
    conv = Path(tarefa['conv'])
    analise_dir = conv / 'analise'
    if tarefa['tipo'] == 'converter' or not (analise_dir / 'analise.json').exists():
        transcricao.analisar(mistura, stem, cache / 'vocal.flac', inst['id'], analise_dir,
                             caminhos.MODELOS_AUDIO / mega53.BEAT_THIS['arquivo'], progresso=progresso)
    analise, curvas = transcricao.carregar_analise(analise_dir)
    if not analise['trechos']:
        presencas = ', '.join(f'{s} {round(v * 100)}%' for s, v in (info_sep.get('presenca') or {}).items()
                              if s != 'vocal')
        raise ErroConversao(f"Não encontrei {inst['nome'].lower()} nesta gravação (presença dos stems: {presencas}). "
                            'Confira o instrumento escolhido; trocar de instrumento não exige separar de novo.')
    n, vdir = _proxima_versao(conv)
    musica = tarefa.get('musica') or {}
    res = transcricao.gerar(analise, curvas, stem, vdir, tarefa.get('ajustes'), musica.get('titulo') or 'Partitura',
                            musica.get('compositor'), pdf=(tarefa.get('opcoes') or {}).get('pdf', True),
                            progresso=progresso)
    (vdir / 'versao.json').write_text(json.dumps(
        {'versao': n, 'quando': datetime.now().isoformat(timespec='seconds'), 'instrumento': inst['id'],
         'ajustes': tarefa.get('ajustes') or {}, 'segmentacao': analise['segmentacao']}, ensure_ascii=False,
        indent=2), encoding='utf-8')
    publicados = {}
    saida = tarefa.get('saida') or {}
    if saida.get('pasta'):
        progresso('publicando', 'Salvando na pasta de saída', None, None)
        arquivos = {ext: p for ext, p in res['arquivos'].items() if p and ext in ('.mscz', '.pdf')}
        publicados = publicar.publicar(arquivos, saida['pasta'], saida.get('nome') or 'Partitura',
                                       bool(tarefa.get('substituir')))
    rel = res['conferencia']
    return {'ok': True, 'versao': n, 'pasta_versao': str(vdir),
            'publicados': {k: str(v) for k, v in publicados.items()},
            'resumo': {'total': rel['total'], 'esperado': None, 'diferenca': None, 'alertas': rel['alertas'],
                       'trechos': len(rel['trechos']), 'notas': rel['notas'], 'baixa_confianca': rel['baixa_confianca'],
                       'fora_extensao': len(rel['fora_extensao']), 'bpm': rel['bpm'], 'compasso': rel['compasso'],
                       'tom': rel['tom_escrito']},
            'conversao': {'separacao': {k: info_sep.get(k) for k in ('modelo', 'dispositivo', 'trecho_s', 'segundos',
                                                                      'cache')},
                          'instrumento': inst['id'], 'segmentacao': analise['segmentacao']},
            'audio': {'presenca': info_sep.get('presenca')}}


def executar(tarefa):
    def progresso(etapa, msg, i=None, n=None):
        emitir(etapa=etapa, msg=msg, i=i, n=n)

    if tarefa.get('tipo') == 'baixar':
        from . import baixar
        return baixar.executar(tarefa, progresso)
    if tarefa.get('tipo') in ('converter', 'acabar'):
        return converter(tarefa, progresso)
    raise ErroConversao(f"Tipo de trabalho desconhecido: {tarefa.get('tipo')}")


def main():
    _isolar_saida()
    _ambiente()
    tarefa = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
    try:
        resultado = executar(tarefa)
    except ErroConversao as e:
        resultado = {'ok': False, 'erro': str(e)}
    except Exception as e:  # noqa: BLE001 — qualquer falha vira mensagem para a interface
        traceback.print_exc()
        resultado = {'ok': False, 'erro': f'Erro inesperado: {e}', 'detalhe': traceback.format_exc()}
    emitir(fim=True, **resultado)
    sys.exit(0 if resultado['ok'] else 1)


if __name__ == '__main__':
    main()

"""Executa UMA tarefa da fila num processo separado (o servidor nunca converte dentro de si).

Uso: python -m partituras.trabalho tarefa.json

A tarefa (JSON) traz: tipo ('converter' | 'acabar'), conv (pasta da conversão), paginas [{caminho, giro}],
opcoes, correcoes, saida {pasta, nome}, substituir. O progresso sai em linhas JSON na saída padrão; a
última linha tem "fim": true. Cancelar = o servidor encerra o grupo de processos (motores incluídos).
"""
import json
import sys
import traceback
from pathlib import Path

from . import pipeline
from .erros import ErroConversao


def emitir(**dados):
    print(json.dumps(dados, ensure_ascii=False), flush=True)


def executar(tarefa):
    def progresso(etapa, msg, i=None, n=None):
        emitir(etapa=etapa, msg=msg, i=i, n=n)

    opcoes = pipeline.Opcoes.de_dict(tarefa.get('opcoes'))
    conv = Path(tarefa['conv'])
    if tarefa.get('tipo', 'converter') == 'converter':
        paginas = [pipeline.Pagina(Path(p['caminho']), int(p.get('giro', 0))) for p in tarefa['paginas']]
        pipeline.reconhecer(paginas, conv, opcoes, progresso)
    res = pipeline.acabar(conv, opcoes, tarefa.get('correcoes'), progresso)
    saida = tarefa.get('saida') or {}
    publicados = {}
    if saida.get('pasta'):
        progresso('publicando', 'Salvando na pasta de saída', None, None)
        publicados = pipeline.publicar_versao(res, saida['pasta'], saida.get('nome') or 'Partitura',
                                              bool(tarefa.get('substituir')))
    rel = res['conferencia']
    return {'ok': True, 'versao': res['versao'], 'pasta_versao': str(res['pasta']),
            'publicados': {k: str(v) for k, v in publicados.items()},
            'resumo': {'total': rel['total'], 'esperado': rel['esperado'], 'diferenca': rel['diferenca'],
                       'alertas': rel['alertas'], 'trechos': len(rel['trechos']),
                       'duracao_errada': len(rel['duracao_errada']), 'suspeitos': len(rel['suspeitos']),
                       'ligaduras': len(rel['ligaduras'])}}


def main():
    tarefa = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
    try:
        resultado = executar(tarefa)
    except ErroConversao as e:
        resultado = {'ok': False, 'erro': str(e)}
    except Exception as e:  # noqa: BLE001 — qualquer falha vira mensagem para a interface
        resultado = {'ok': False, 'erro': f'Erro inesperado: {e}', 'detalhe': traceback.format_exc()}
    emitir(fim=True, **resultado)
    sys.exit(0 if resultado['ok'] else 1)


if __name__ == '__main__':
    main()

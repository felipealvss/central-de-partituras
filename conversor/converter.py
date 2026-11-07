#!/usr/bin/env python3
"""Linha de comando do conversor. A interface gráfica (Central de Partituras) usa o mesmo núcleo: partituras/.

Exemplos (pelo atalho ./converter):
    ./converter pagina1.heic pagina2.heic -o "Minha musica.mscz"
    ./converter pagina1.heic pagina2.heic -o hino.mscz --motor ambos --ultimo-compasso 165 --pdf
    ./converter fotos/*.heic -o hino.mscz --corrigir "1=11,2=19,3=37"     (corrige trechos de pausa)

Nunca sobrescreve: se o nome existir, grava "Nome (2).mscz". Use --substituir para mandar o antigo à Lixeira.
"""
import argparse
import shutil
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from partituras import caminhos, pipeline  # noqa: E402
from partituras.erros import ErroConversao  # noqa: E402


def _correcoes(texto):
    if not texto:
        return None
    pares = {}
    for item in texto.split(','):
        chave, _, valor = item.partition('=')
        pares[int(chave)] = int(valor)
    return pares


def _mostrar(_etapa, msg, i=None, n=None):
    print(f'  {msg}', flush=True)


def main():
    ap = argparse.ArgumentParser(description='Converte fotos (HEIC/JPG/PNG) ou PDF de partitura em .mscz (MuseScore).')
    ap.add_argument('entradas', nargs='+', help='páginas na ordem (fotos ou PDF)')
    ap.add_argument('-o', '--saida', required=True, help='arquivo .mscz de saída')
    ap.add_argument('--motor', choices=['homr', 'audiveris', 'ambos'], default='homr',
                    help='homr (padrão, melhor para fotos), audiveris (dinâmicas e textos) ou ambos (para comparar)')
    ap.add_argument('--titulo', help='título da obra')
    ap.add_argument('--instrumento', help='nome do instrumento/parte')
    ap.add_argument('--compositor', help='compositor/arranjador mostrado no cabeçalho')
    ap.add_argument('--ultimo-compasso', type=int, help='último número de compasso impresso (confere o total)')
    ap.add_argument('--corrigir', help='corrige trechos de pausa: "1=11,2=19" (número do trecho = compassos certos)')
    ap.add_argument('--pdf', action='store_true', help='também gera um PDF do resultado, para comparar com o original')
    ap.add_argument('--guias', choices=['fa', 'sol'], help='gera imagens com guias de altura (usa o Audiveris)')
    ap.add_argument('--substituir', action='store_true', help='manda arquivos com o mesmo nome para a Lixeira')
    ap.add_argument('--manter', action='store_true', help='mantém a pasta de trabalho (bruto, versões, logs)')
    args = ap.parse_args()

    destino = Path(args.saida).expanduser().resolve()
    if destino.suffix.lower() != '.mscz':
        destino = destino.parent / (destino.name + '.mscz')
    paginas = [pipeline.Pagina(Path(e).expanduser().resolve()) for e in args.entradas]
    motores = ['homr', 'audiveris'] if args.motor == 'ambos' else [args.motor]
    extensoes = ('.mscz', '-conferencia.txt') + (('.pdf',) if args.pdf else ())
    base = caminhos.pasta_trabalho('cli-' + datetime.now().strftime('%Y%m%d-%H%M%S'))
    codigo = 0
    try:
        for motor in motores:
            opcoes = pipeline.Opcoes(motor=motor, titulo=args.titulo, instrumento=args.instrumento,
                                     compositor=args.compositor, pdf=args.pdf, guias=args.guias,
                                     ultimo_compasso=args.ultimo_compasso)
            nome = destino.stem if len(motores) == 1 else f'{destino.stem} ({motor})'
            print(f'== {motor} ==', flush=True)
            res = pipeline.converter(paginas, base / motor, opcoes, destino.parent, nome, _correcoes(args.corrigir),
                                     args.substituir, progresso=_mostrar, extensoes=extensoes)
            pub = res['publicados']
            print(f"\nPronto: {pub['.mscz']}\n{res['texto']}\n", flush=True)
            if args.guias and (base / motor / 'guias').exists():
                alvo = destino.parent / f"{pub['.mscz'].stem}-guias"
                if alvo.exists():
                    print(f'Guias não copiadas: {alvo.name} já existe.')
                else:
                    shutil.copytree(base / motor / 'guias', alvo)
                    print(f'Guias de altura em: {alvo}')
    except ErroConversao as e:
        print(f'Erro: {e}', file=sys.stderr)
        codigo = 1
    except KeyboardInterrupt:
        print('Cancelado.', file=sys.stderr)
        codigo = 130
    finally:
        if args.manter:
            print(f'Pasta de trabalho mantida em: {base}')
        else:
            shutil.rmtree(base, ignore_errors=True)
    sys.exit(codigo)


if __name__ == '__main__':
    main()

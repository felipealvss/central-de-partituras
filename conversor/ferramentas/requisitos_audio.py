"""Gera conversor/requisitos-audio.txt a partir do requisitos-audio.in (ferramenta de desenvolvimento).

    .venv/bin/python ferramentas/requisitos_audio.py [--restricoes ARQUIVO]

Resolve com o uv para Linux x86_64 e Python 3.12 (o .venv-audio), com o hash de cada arquivo, e deixa só os
hashes das rodas que servem nessa plataforma (a saída do uv traz os de todas: Windows, macOS, ARM...).
--restricoes fixa as versões de um ambiente já validado (por exemplo, a saída de `uv pip freeze` dele).
O uv vem de $UV, do .venv (o instalar.sh --audio põe lá) ou do PATH.
"""
import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

AQUI = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AQUI))
from partituras.audio import instalar  # noqa: E402

CABECALHO = """\
# Gerado por ferramentas/requisitos_audio.py a partir do requisitos-audio.in: não edite à mão.
# Linux x86_64 e Python 3.12 (o conversor/.venv-audio): só os hashes das rodas que servem aí.
# O instalar.sh --audio baixa as rodas (partituras/audio/instalar.py) e instala com:
#   uv pip install --offline --no-index --find-links <rodas baixadas> -r requisitos-audio.txt
"""


def achar_uv():
    for c in (os.environ.get('UV'), AQUI / '.venv' / 'bin' / 'uv', shutil.which('uv')):
        if c and Path(c).is_file():
            return str(c)
    raise SystemExit('Não achei o uv: defina UV=/caminho/do/uv.')


def compilar(uv, entrada, restricoes, saida):
    cmd = [uv, 'pip', 'compile', str(entrada), '--generate-hashes', '--python-platform', 'x86_64-manylinux_2_28',
           '--python-version', '3.12', '--no-header', '--no-annotate', '-q', '-o', str(saida)]
    if restricoes:  # copiadas: um <(...) do bash é um /dev/fd que o uv, neto deste processo, não herda
        copia = Path(saida).with_name('restricoes.txt')
        copia.write_text(Path(restricoes).read_text(encoding='utf-8'), encoding='utf-8')
        cmd += ['-c', str(copia)]
    subprocess.run(cmd, check=True, env={**os.environ, 'UV_NO_CONFIG': '1'})


def reduzir(compilado, consulta=instalar.arquivos_pypi):
    pacotes = instalar.ler_requisitos(compilado)
    with ThreadPoolExecutor(8) as ex:
        listas = dict(zip(pacotes, ex.map(lambda n: consulta(n, pacotes[n][0]), pacotes)))
    linhas = []
    for nome in sorted(pacotes):
        versao, hashes = pacotes[nome]
        servem = sorted({a['digests']['sha256'] for a in listas[nome] if a['digests']['sha256'] in hashes
                         and instalar.prioridade(a['filename'], libc=(99, 99))})
        if not servem:  # sem roda para Linux x86_64: fica o código-fonte
            servem = sorted({a['digests']['sha256'] for a in listas[nome]
                             if a['digests']['sha256'] in hashes and a['packagetype'] == 'sdist'})
        if not servem:
            raise SystemExit(f'{nome}=={versao}: nenhum arquivo serve para Linux x86_64 / Python 3.12')
        linhas.append(f'{nome}=={versao} \\\n' + ' \\\n'.join(f'    --hash=sha256:{h}' for h in servem))
    return CABECALHO + '\n'.join(linhas) + '\n'


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--restricoes', type=Path)
    a = p.parse_args()
    with tempfile.TemporaryDirectory() as tmp:
        bruto = Path(tmp) / 'compilado.txt'
        compilar(achar_uv(), AQUI / 'requisitos-audio.in', a.restricoes, bruto)
        texto = reduzir(bruto)
    (AQUI / 'requisitos-audio.txt').write_text(texto, encoding='utf-8')
    print(f"requisitos-audio.txt: {texto.count('==')} pacotes, {texto.count('--hash')} hashes")


if __name__ == '__main__':
    main()

"""Instalação do modo de áudio, chamada pelo conversor/instalar.sh --audio. Só biblioteca padrão.

    python -m partituras.audio.instalar rodas <requisitos.txt> <pasta> [--python PY]   # baixa as rodas
    python -m partituras.audio.instalar modelos                                         # baixa e confere os modelos
    python -m partituras.audio.instalar node                                            # caminho do Node.js

Por que baixar aqui, e não deixar o uv baixar: na conexão em que o modo de áudio foi testado, cada download
ficava às vezes em ~200 KB/s, e numa instalação o uv ficou horas parado num download empacado, sem mostrar nada.
O aria2c baixa em várias conexões, refaz as que travam e retoma o que foi interrompido; sem ele, o curl baixa
quatro arquivos por vez e desiste de uma conexão parada (e o instalador retoma na próxima vez). Depois o uv
instala sem rede (--offline --no-index), só das rodas baixadas. Com --python, baixa só o que falta no ambiente
(rodar o instalador de novo não baixa tudo outra vez). Tudo é conferido pelo SHA-256: as rodas, pelo
requisitos-audio.txt (o uv confere de novo ao instalar); os modelos, pelo mega53.py.
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

from .. import caminhos
from . import mega53

PYTHON_ALVO = (3, 12)          # o Python do .venv-audio (o uv cria), não o deste processo
PYPI = 'https://pypi.org/pypi/{nome}/{versao}/json'
_LEGADO = {'manylinux1_x86_64': (2, 5), 'manylinux2010_x86_64': (2, 12), 'manylinux2014_x86_64': (2, 17)}


def sha256(arquivo, bloco=1 << 22):
    h = hashlib.sha256()
    with open(arquivo, 'rb') as f:
        while bloco_lido := f.read(bloco):
            h.update(bloco_lido)
    return h.hexdigest()


def _confere(arquivo, esperado, tamanho=None):
    arquivo = Path(arquivo)
    return (arquivo.is_file() and (tamanho is None or arquivo.stat().st_size == tamanho)
            and sha256(arquivo) == esperado)


def glibc():
    try:
        return tuple(int(x) for x in os.confstr('CS_GNU_LIBC_VERSION').split()[1].split('.')[:2])
    except (ValueError, OSError, IndexError, AttributeError):
        return (2, 28)


# ------------------------------------------------------------------ rodas
def _tags(nome_arquivo):
    if not nome_arquivo.endswith('.whl'):
        return None
    partes = nome_arquivo[:-4].split('-')
    if len(partes) not in (5, 6):
        return None
    return partes[-3].split('.'), partes[-2].split('.'), partes[-1].split('.')


def _nivel_python(pys, abis, py):
    """3 = feita para este CPython; 2 = abi3 (vale para ele); 1 = Python puro; 0 = não serve."""
    cp = f'cp{py[0]}{py[1]}'
    nivel = 0
    for t in pys:
        for a in abis:
            m = re.fullmatch(rf'cp{py[0]}(\d+)', t)
            if a == cp and t == cp:
                nivel = max(nivel, 3)
            elif a == 'abi3' and m and int(m.group(1)) <= py[1]:
                nivel = max(nivel, 2)
            elif a == 'none' and t in (cp, f'py{py[0]}', f'py{py[0]}{py[1]}'):
                nivel = max(nivel, 1)
    return nivel


def _nivel_plataforma(plats, libc):
    """Maior glibc exigida que este sistema atende ((0, 0) = qualquer plataforma); None = não serve."""
    melhor = None
    for p in plats:
        if p == 'any':
            v = (0, 0)
        elif p in _LEGADO:
            v = _LEGADO[p]
        else:
            m = re.fullmatch(r'manylinux_(\d+)_(\d+)_x86_64', p)
            v = (int(m.group(1)), int(m.group(2))) if m else None
        if v is not None and v <= libc and (melhor is None or v > melhor):
            melhor = v
    return melhor


def prioridade(nome_arquivo, py=PYTHON_ALVO, libc=None):
    """Chave de escolha entre rodas de uma mesma versão (maior = melhor); None se a roda não instala no
    Python alvo em Linux x86_64. Segue a preferência do uv/pip: a roda mais específica."""
    tags = _tags(nome_arquivo)
    if not tags:
        return None
    pys, abis, plats = tags
    n_py = _nivel_python(pys, abis, py)
    n_plat = _nivel_plataforma(plats, libc or glibc())
    if not n_py or n_plat is None:
        return None
    return (n_py, n_plat)


def ler_requisitos(arquivo):
    """{nome normalizado: (versão, {sha256})} de um requirements gerado pelo uv pip compile --generate-hashes."""
    texto = re.sub(r'\\\s*\n', ' ', Path(arquivo).read_text(encoding='utf-8'))
    pacotes = {}
    for linha in texto.splitlines():
        linha = linha.strip()
        if not linha or linha.startswith(('#', '-')):
            continue
        m = re.match(r'([A-Za-z0-9][A-Za-z0-9._-]*)(?:\[[^\]]*\])?\s*==\s*([^\s;\\]+)', linha)
        if m:
            nome = re.sub(r'[-_.]+', '-', m.group(1)).lower()
            pacotes[nome] = (m.group(2), set(re.findall(r'--hash=sha256:([0-9a-f]{64})', linha)))
    return pacotes


def arquivos_pypi(nome, versao):
    with urllib.request.urlopen(PYPI.format(nome=nome, versao=versao), timeout=60) as r:
        return json.load(r)['urls']


def escolher_roda(arquivos, hashes, py=PYTHON_ALVO, libc=None):
    """A roda que o uv vai querer: das que estão no requisitos (pelo hash) e servem aqui, a mais específica."""
    candidatos = []
    for a in arquivos:
        chave = prioridade(a['filename'], py, libc)
        if chave and a['digests']['sha256'] in hashes and not a.get('yanked'):
            candidatos.append((chave, a))
    return max(candidatos, key=lambda c: c[0])[1] if candidatos else None


def instalados(python):
    """{nome normalizado: versão} do que já está instalado no ambiente desse Python ({} se ele não existe)."""
    if not python or not Path(python).exists():
        return {}
    r = subprocess.run([str(python), '-c', 'import importlib.metadata as m, json; print(json.dumps('
                        '{d.metadata["Name"]: d.version for d in m.distributions()}))'],
                       capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        return {}
    return {re.sub(r'[-_.]+', '-', n).lower(): v for n, v in json.loads(r.stdout).items()}


def _baixar_lote(pendentes, pasta, aria2c, curl):
    if aria2c:
        lista = pasta / 'aria2c.txt'
        lista.write_text(''.join(f"{a['url']}\n  out={a['filename']}\n  checksum=sha-256={a['digests']['sha256']}\n"
                                 for a in pendentes), encoding='utf-8')
        subprocess.run([aria2c, '--input-file', str(lista), '--dir', str(pasta), '--max-concurrent-downloads=4',
                        '--split=16', '--max-connection-per-server=16', '--min-split-size=1M', '--continue=true',
                        '--allow-overwrite=true', '--auto-file-renaming=false', '--file-allocation=none',
                        '--console-log-level=warn', '--summary-interval=0', '--download-result=hide',
                        '--max-tries=10', '--retry-wait=3', '--timeout=60'], check=True)
        lista.unlink(missing_ok=True)
        return

    def um(a):  # sem o aria2c: uma conexão por arquivo; parada por 60 s, desiste e tenta de novo
        subprocess.run([curl, '-fL', '-sS', '--retry', '5', '--retry-delay', '3', '--speed-limit', '2048',
                        '--speed-time', '60', '-C', '-', '-o', str(pasta / a['filename']), a['url']], check=True)
        print(f"    {a['filename']}", flush=True)
    with ThreadPoolExecutor(4) as ex:
        list(ex.map(um, pendentes))


def rodas(requisitos, pasta, python=None, minimo=0, aria2c=None, curl=None, consulta=arquivos_pypi,
          simular=False, ja_instalados=None):
    """Baixa para `pasta` as rodas do requisitos que faltam no ambiente de `python`, conferidas pelo hash.
    Devolve a lista das rodas escolhidas (as que faltam)."""
    aria2c = shutil.which('aria2c') if aria2c is None else aria2c
    curl = curl or shutil.which('curl') or 'curl'
    pacotes = ler_requisitos(requisitos)
    feitos = instalados(python) if ja_instalados is None else ja_instalados
    faltam = {n: vh for n, vh in pacotes.items() if feitos.get(n) != vh[0]}
    if not faltam:
        print(f'  As {len(pacotes)} bibliotecas já estão instaladas nas versões do requisitos.', flush=True)
        return []
    libc = glibc()
    with ThreadPoolExecutor(8) as ex:
        listas = dict(zip(faltam, ex.map(lambda n: consulta(n, faltam[n][0]), faltam)))
    escolhidas = []
    for nome, (versao, hashes) in faltam.items():
        a = escolher_roda(listas[nome], hashes, libc=libc)
        if not a:
            raise SystemExit(f'Nenhum arquivo de {nome}=={versao} serve para Linux x86_64 com Python 3.12.')
        if a['size'] >= minimo:
            escolhidas.append(a)
    pasta = Path(pasta)
    pendentes = [a for a in escolhidas if not _confere(pasta / a['filename'], a['digests']['sha256'], a['size'])]
    print(f"  {len(escolhidas)} de {len(pacotes)} bibliotecas a instalar "
          f"({sum(a['size'] for a in escolhidas) / 1e9:.2f} GB); a baixar: {len(pendentes)} "
          f"({sum(a['size'] for a in pendentes) / 1e9:.2f} GB){'' if aria2c else ', pelo curl (sem o aria2c)'}",
          flush=True)
    if simular or not pendentes:
        return escolhidas
    pasta.mkdir(parents=True, exist_ok=True)
    _baixar_lote(pendentes, pasta, aria2c, curl)
    for a in pendentes:
        if not _confere(pasta / a['filename'], a['digests']['sha256'], a['size']):
            (pasta / a['filename']).unlink(missing_ok=True)
            raise SystemExit(f"A roda {a['filename']} não confere com o hash do requisitos-audio.txt; rode de novo.")
    return escolhidas


# ------------------------------------------------------------------ modelos
def baixar_arquivo(url, destino, aria2c=None, curl=None):
    """url → destino, retomando um download interrompido. Não confere nada: quem chama confere o hash."""
    destino = Path(destino)
    aria2c = shutil.which('aria2c') if aria2c is None else aria2c
    if aria2c and url.startswith(('https://', 'http://')):
        cmd = [aria2c, '--dir', str(destino.parent), '--out', destino.name, '--split=16',
               '--max-connection-per-server=16', '--min-split-size=1M', '--continue=true', '--allow-overwrite=true',
               '--auto-file-renaming=false', '--file-allocation=none', '--console-log-level=warn',
               '--summary-interval=0', '--max-tries=5', '--retry-wait=3', url]
    else:
        cmd = [curl or shutil.which('curl') or 'curl', '-fL', '--retry', '3', '-C', '-',
               '--progress-bar' if sys.stderr.isatty() else '-sS', '-o', str(destino), url]
    subprocess.run(cmd, check=True)


def modelos(pasta=None, lista=mega53.MODELOS, baixar=baixar_arquivo):
    """Baixa o que falta e confere tudo pelo SHA-256; o .verificado (o que disponivel.estado() olha) só é gravado
    no fim, com todos conferidos. Um arquivo que já está aqui e confere não é baixado de novo."""
    pasta = Path(pasta or caminhos.MODELOS_AUDIO)
    pasta.mkdir(parents=True, exist_ok=True)
    marcador = pasta / '.verificado'
    marcador.unlink(missing_ok=True)
    linhas = []
    for m in lista:
        final = pasta / m['arquivo']
        if _confere(final, m['sha256'], m['tamanho']):
            print(f"  {m['arquivo']}: confere")
        else:
            final.unlink(missing_ok=True)
            parcial = pasta / f"{m['arquivo']}.parcial"
            if parcial.exists() and parcial.stat().st_size >= m['tamanho']:
                parcial.unlink()  # completo mas não conferiu antes: começa de novo
            print(f"  {m['arquivo']}: baixando {m['tamanho'] / 1e6:.0f} MB…")
            baixar(m['url'], parcial)
            if not _confere(parcial, m['sha256'], m['tamanho']):
                parcial.unlink(missing_ok=True)
                raise SystemExit(f"O arquivo baixado de {m['url']} não confere com o SHA-256 esperado. "
                                 'Rode o instalador de novo.')
            os.replace(parcial, final)
            print(f"  {m['arquivo']}: baixado e conferido")
        linhas.append(f"{m['sha256']}  {m['arquivo']}")
    marcador.write_text(datetime.now().astimezone().isoformat(timespec='seconds') + '\n' + '\n'.join(linhas) + '\n',
                        encoding='utf-8')
    return linhas


# ------------------------------------------------------------------ Node.js
def node(pasta=None, procurar=shutil.which):
    """Grava o caminho real do Node.js: o atalho do menu não herda o PATH do terminal, e gerenciadores como o
    fnm põem no PATH um link temporário."""
    destino = Path(pasta or caminhos.MODELOS_AUDIO) / 'node.txt'
    achado = procurar('node')
    if not achado:
        destino.unlink(missing_ok=True)
        print('  Aviso: Node.js não encontrado. Sem ele, importar por link não funciona '
              '(no Fedora: sudo dnf install nodejs); o resto do modo de áudio funciona.')
        return None
    real = os.path.realpath(achado)
    try:
        versao = subprocess.run([real, '--version'], capture_output=True, text=True, timeout=30).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        versao = '?'
    m = re.match(r'v(\d+)', versao)
    if m and int(m.group(1)) < 20:
        print(f'  Aviso: o Node.js {versao} é antigo; se importar por link falhar, atualize-o.')
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(real + '\n', encoding='utf-8')
    print(f'  Node.js {versao}: {real}')
    return real


def main(args=None):
    args = list(sys.argv[1:] if args is None else args)
    try:
        if args[:1] == ['rodas'] and len(args) >= 3:
            opcoes = args[3:]
            python = opcoes[opcoes.index('--python') + 1] if '--python' in opcoes[:-1] else None
            rodas(args[1], args[2], python=python, simular='--simular' in opcoes)
        elif args == ['modelos']:
            modelos()
        elif args == ['node']:
            node()
        else:
            raise SystemExit(__doc__)
    except subprocess.CalledProcessError as e:
        raise SystemExit(f'O download falhou ({Path(e.cmd[0]).name} terminou com o código {e.returncode}). '
                         'Rode o instalador de novo: ele continua de onde parou.') from None


if __name__ == '__main__':
    main()

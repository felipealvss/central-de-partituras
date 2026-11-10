"""Instalação do modo de áudio (partituras/audio/instalar.py e as opções do instalar.sh), sem rede.

Os downloads usam URLs file:// — o curl de verdade para os modelos e um aria2c falso para as rodas — e o
instalar.sh roda só nos caminhos que não instalam nada (ajuda, opção errada, atualizar sem o modo de áudio).
"""
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

from partituras.audio import instalar

CONVERSOR = Path(__file__).resolve().parents[1]
LIBC = (2, 43)

ARIA2C_FALSO = textwrap.dedent('''\
    #!PYTHON
    """aria2c falso: --input-file com "url / out= / checksum=sha-256=", ou --dir/--out e uma URL; só file://."""
    import hashlib, shutil, sys
    from pathlib import Path
    args = sys.argv[1:]
    op = {a.split('=', 1)[0]: (a.split('=', 1)[1] if '=' in a else None) for a in args if a.startswith('--')}
    def valor(nome):
        if op.get(nome):
            return op[nome]
        return args[args.index(nome) + 1]
    pasta = Path(valor('--dir'))
    if '--input-file' in op or '--input-file' in args:
        itens, atual = [], None
        for linha in Path(valor('--input-file')).read_text().splitlines():
            if not linha.startswith(' '):
                atual = {'url': linha.strip()}; itens.append(atual)
            else:
                k, v = linha.strip().split('=', 1); atual[k] = v
    else:
        itens = [{'url': args[-1], 'out': valor('--out')}]
    for it in itens:
        destino = pasta / it['out']
        shutil.copyfile(it['url'][len('file://'):], destino)
        esperado = it.get('checksum', '').replace('sha-256=', '')
        if esperado and hashlib.sha256(destino.read_bytes()).hexdigest() != esperado:
            sys.exit(32)
    ''')


def _sha(dados):
    return hashlib.sha256(dados).hexdigest()


class TestRodas(unittest.TestCase):
    def test_compatibilidade_com_python_312_em_linux_x86_64(self):
        casos = {
            'torch-2.15.0-cp312-cp312-manylinux_2_28_x86_64.whl': (3, (2, 28)),
            'triton-3.9.0-cp312-abi3-manylinux_2_27_x86_64.manylinux_2_28_x86_64.whl': (2, (2, 28)),
            'x-1.0-cp39-abi3-manylinux2014_x86_64.whl': (2, (2, 17)),
            'nvidia_cublas-13.4.1.3-py3-none-manylinux_2_27_x86_64.whl': (1, (2, 27)),
            'einops-0.8.2-py3-none-any.whl': (1, (0, 0)),
            'six-1.0-py2.py3-none-any.whl': (1, (0, 0)),
            'x-1.0-1-cp312-cp312-manylinux1_x86_64.whl': (3, (2, 5)),
        }
        for nome, esperado in casos.items():
            with self.subTest(nome):
                self.assertEqual(instalar.prioridade(nome, libc=LIBC), esperado)
        for nome in ('numpy-2.5.4-cp313-cp313-manylinux_2_28_x86_64.whl', 'x-1.0-cp313-abi3-manylinux_2_17_x86_64.whl',
                     'x-1.0-cp312-cp312-win_amd64.whl', 'x-1.0-cp312-cp312-macosx_11_0_arm64.whl',
                     'x-1.0-cp312-cp312-manylinux_2_28_aarch64.whl', 'x-1.0-cp312-cp312-manylinux_2_45_x86_64.whl',
                     'x-1.0-cp312-cp312-musllinux_1_2_x86_64.whl', 'x-1.0.tar.gz', 'x-1.0-py3-none-any.zip'):
            with self.subTest(nome):
                self.assertIsNone(instalar.prioridade(nome, libc=LIBC))

    def test_escolhe_a_roda_mais_especifica_que_esta_no_requisitos(self):
        def arq(nome, h, **extra):
            return {'filename': nome, 'digests': {'sha256': h}, 'size': 1, 'url': f'https://x/{nome}', **extra}
        arquivos = [arq('x-1.0.tar.gz', 'a'), arq('x-1.0-py3-none-any.whl', 'b'),
                    arq('x-1.0-cp312-cp312-manylinux_2_17_x86_64.whl', 'c'),
                    arq('x-1.0-cp312-cp312-manylinux_2_28_x86_64.whl', 'd'),
                    arq('x-1.0-cp313-cp313-manylinux_2_28_x86_64.whl', 'e'),
                    arq('x-1.0-cp312-cp312-manylinux_2_34_x86_64.whl', 'f', yanked=True)]
        escolha = lambda hashes: (instalar.escolher_roda(arquivos, hashes, libc=LIBC) or {}).get('filename')
        self.assertEqual(escolha(set('abcdef')), 'x-1.0-cp312-cp312-manylinux_2_28_x86_64.whl')
        self.assertEqual(escolha(set('abc')), 'x-1.0-cp312-cp312-manylinux_2_17_x86_64.whl')
        self.assertEqual(escolha({'a', 'b'}), 'x-1.0-py3-none-any.whl')
        self.assertIsNone(escolha({'a', 'e', 'f'}))

    def test_le_o_requisitos_gerado_pelo_uv(self):
        tmp = Path(tempfile.mkdtemp(prefix='central-teste-'))
        self.addCleanup(shutil.rmtree, tmp, True)
        (tmp / 'r.txt').write_text(textwrap.dedent('''\
            # comentário
            beat-this==1.1.0 \\
                --hash=sha256:''' + '1' * 64 + ''' \\
                --hash=sha256:''' + '2' * 64 + '''
            Rotary_Embedding.Torch==0.9.2 \\
                --hash=sha256:''' + '3' * 64 + '''
            yt-dlp[default]==2026.10.26 ; sys_platform == "linux" \\
                --hash=sha256:''' + '4' * 64 + '''
            --find-links rodas
            '''))
        r = instalar.ler_requisitos(tmp / 'r.txt')
        self.assertEqual(r, {'beat-this': ('1.1.0', {'1' * 64, '2' * 64}),
                             'rotary-embedding-torch': ('0.9.2', {'3' * 64}),
                             'yt-dlp': ('2026.10.26', {'4' * 64})})

    def test_requisitos_do_repositorio_fixa_tudo_com_hash(self):
        r = instalar.ler_requisitos(CONVERSOR / 'requisitos-audio.txt')
        self.assertGreater(len(r), 50)
        self.assertTrue(all(v and h for v, h in r.values()))
        for nome in ('torch', 'librosa', 'music21', 'beat-this', 'soxr', 'einops', 'beartype',
                     'rotary-embedding-torch', 'matplotlib', 'mir-eval'):
            self.assertIn(nome, r)
        self.assertNotIn('yt-dlp', r)  # sempre a versão mais nova, à parte
        entrada = (CONVERSOR / 'requisitos-audio.in').read_text(encoding='utf-8')
        for linha in entrada.splitlines():
            if linha and not linha.startswith('#'):
                nome, versao = linha.split('==')
                self.assertEqual(r[nome][0], versao, nome)

    def _cenario(self):
        tmp = Path(tempfile.mkdtemp(prefix='central-teste-'))
        self.addCleanup(shutil.rmtree, tmp, True)
        origem = tmp / 'origem'
        origem.mkdir()
        conteudo = {'grande-1.0-py3-none-any.whl': b'G' * 3000, 'pequena-1.0-py3-none-any.whl': b'p' * 10,
                    'outra-2.0-py3-none-any.whl': b'O' * 2000, 'feita-3.0-py3-none-any.whl': b'F' * 50}
        for nome, dados in conteudo.items():
            (origem / nome).write_bytes(dados)
        pypi = {n.split('-')[0]: [{'filename': n, 'digests': {'sha256': _sha(d)}, 'size': len(d),
                                   'url': f'file://{origem / n}'}] for n, d in conteudo.items()}
        req = tmp / 'r.txt'
        req.write_text(''.join(f"{n.split('-')[0]}=={n.split('-')[1]} --hash=sha256:{_sha(d)}\n"
                               for n, d in conteudo.items()))
        aria = tmp / 'aria2c'
        aria.write_text(ARIA2C_FALSO.replace('PYTHON', sys.executable))
        aria.chmod(0o755)
        return tmp, origem, req, aria, (lambda n, v: pypi[n])

    def test_baixa_so_o_que_falta_e_confere(self):
        tmp, origem, req, aria, consulta = self._cenario()
        rodas = tmp / 'rodas'
        rodas.mkdir()
        (rodas / 'outra-2.0-py3-none-any.whl').write_bytes(b'O' * 2000)  # já baixada antes
        antes = (rodas / 'outra-2.0-py3-none-any.whl').stat().st_mtime_ns
        feitos = {'feita': '3.0', 'grande': '0.9'}  # a "feita" já está instalada; a "grande", noutra versão
        escolhidas = instalar.rodas(req, rodas, aria2c=str(aria), consulta=consulta, ja_instalados=feitos)
        self.assertEqual(sorted(a['filename'] for a in escolhidas),
                         ['grande-1.0-py3-none-any.whl', 'outra-2.0-py3-none-any.whl', 'pequena-1.0-py3-none-any.whl'])
        self.assertEqual((rodas / 'grande-1.0-py3-none-any.whl').read_bytes(), b'G' * 3000)
        self.assertFalse((rodas / 'feita-3.0-py3-none-any.whl').exists())
        self.assertEqual((rodas / 'outra-2.0-py3-none-any.whl').stat().st_mtime_ns, antes)
        self.assertEqual(sorted(p.name for p in rodas.iterdir()),
                         ['grande-1.0-py3-none-any.whl', 'outra-2.0-py3-none-any.whl', 'pequena-1.0-py3-none-any.whl'])
        # na origem, um arquivo diferente do que o requisitos espera: o aria2c recusa
        (rodas / 'grande-1.0-py3-none-any.whl').unlink()
        (origem / 'grande-1.0-py3-none-any.whl').write_bytes(b'X' * 3000)
        with self.assertRaises((SystemExit, subprocess.CalledProcessError)):
            instalar.rodas(req, rodas, aria2c=str(aria), consulta=consulta, ja_instalados=feitos)

    @unittest.skipUnless(shutil.which('curl'), 'sem o curl')
    def test_sem_aria2c_usa_o_curl_e_confere(self):
        tmp, origem, req, _aria, consulta = self._cenario()
        rodas = tmp / 'rodas'
        rodas.mkdir()
        escolhidas = instalar.rodas(req, rodas, aria2c='', consulta=consulta, ja_instalados={})
        self.assertEqual(len(escolhidas), 4)
        self.assertEqual((rodas / 'pequena-1.0-py3-none-any.whl').read_bytes(), b'p' * 10)
        (rodas / 'pequena-1.0-py3-none-any.whl').unlink()
        (origem / 'pequena-1.0-py3-none-any.whl').write_bytes(b'q' * 10)
        with self.assertRaises(SystemExit) as ctx:
            instalar.rodas(req, rodas, aria2c='', consulta=consulta, ja_instalados={})
        self.assertIn('não confere', str(ctx.exception))
        self.assertFalse((rodas / 'pequena-1.0-py3-none-any.whl').exists())

    def test_tudo_instalado_nao_consulta_nem_baixa(self):
        tmp, _origem, req, aria, _consulta = self._cenario()
        feitos = {'grande': '1.0', 'pequena': '1.0', 'outra': '2.0', 'feita': '3.0'}
        self.assertEqual(instalar.rodas(req, tmp / 'rodas', aria2c=str(aria), consulta=None, ja_instalados=feitos), [])
        self.assertFalse((tmp / 'rodas').exists())

    def test_sem_roda_que_sirva_explica(self):
        tmp, _origem, req, aria, _consulta = self._cenario()
        windows = lambda n, v: [{'filename': f'{n}-{v}-cp312-cp312-win_amd64.whl', 'size': 1, 'url': 'file:///x',
                                 'digests': {'sha256': '0' * 64}}]
        with self.assertRaises(SystemExit) as ctx:
            instalar.rodas(req, tmp / 'rodas', aria2c=str(aria), consulta=windows, ja_instalados={})
        self.assertIn('Linux x86_64 com Python 3.12', str(ctx.exception))

    def test_le_o_que_o_ambiente_tem_instalado(self):
        feitos = instalar.instalados(sys.executable)
        self.assertIn('numpy', feitos)  # o .venv-audio, criado pelo uv, não tem o pip
        self.assertTrue(all(n == n.lower() and '_' not in n for n in feitos))
        self.assertEqual(instalar.instalados(Path('/nao/existe/python')), {})


@unittest.skipUnless(shutil.which('curl'), 'sem o curl')
class TestModelos(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='central-teste-'))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.origem = self.tmp / 'origem'
        self.origem.mkdir()
        self.pasta = self.tmp / 'modelos'
        self.lista = []
        for nome, dados in (('a.ckpt', b'modelo A' * 500), ('b.ckpt', b'modelo B' * 300)):
            (self.origem / nome).write_bytes(dados)
            self.lista.append({'arquivo': nome, 'tamanho': len(dados), 'sha256': _sha(dados),
                               'url': f'file://{self.origem / nome}'})
        self.baixados = []

    def baixar(self, url, destino):
        self.baixados.append(Path(destino).name)
        instalar.baixar_arquivo(url, destino, aria2c='')

    def test_baixa_confere_e_nao_baixa_de_novo(self):
        instalar.modelos(self.pasta, self.lista, self.baixar)
        self.assertEqual(self.baixados, ['a.ckpt.parcial', 'b.ckpt.parcial'])
        marcador = (self.pasta / '.verificado').read_text().splitlines()
        self.assertEqual(marcador[1:], [f"{m['sha256']}  {m['arquivo']}" for m in self.lista])
        self.assertEqual(sorted(p.name for p in self.pasta.iterdir()), ['.verificado', 'a.ckpt', 'b.ckpt'])
        instalar.modelos(self.pasta, self.lista, self.baixar)
        self.assertEqual(len(self.baixados), 2)
        # arquivo estragado: baixa de novo só ele
        (self.pasta / 'b.ckpt').write_bytes(b'estragado')
        instalar.modelos(self.pasta, self.lista, self.baixar)
        self.assertEqual(self.baixados[2:], ['b.ckpt.parcial'])

    def test_retoma_download_interrompido(self):
        self.pasta.mkdir()
        dados = (self.origem / 'a.ckpt').read_bytes()
        (self.pasta / 'a.ckpt.parcial').write_bytes(dados[:1000])
        instalar.modelos(self.pasta, self.lista[:1], self.baixar)
        self.assertEqual((self.pasta / 'a.ckpt').read_bytes(), dados)

    def test_hash_errado_nao_marca_como_verificado(self):
        self.lista[1]['sha256'] = '0' * 64
        with self.assertRaises(SystemExit) as ctx:
            instalar.modelos(self.pasta, self.lista, self.baixar)
        self.assertIn('não confere', str(ctx.exception))
        self.assertEqual(sorted(p.name for p in self.pasta.iterdir()), ['a.ckpt'])
        # um .parcial completo mas errado é descartado antes de baixar de novo
        (self.pasta / 'b.ckpt.parcial').write_bytes(b'x' * self.lista[1]['tamanho'])
        self.lista[1]['sha256'] = _sha((self.origem / 'b.ckpt').read_bytes())
        instalar.modelos(self.pasta, self.lista, self.baixar)
        self.assertTrue((self.pasta / '.verificado').exists())

    def test_node_grava_o_caminho_real(self):
        bin_ = self.tmp / 'versoes' / 'v24' / 'bin'
        bin_.mkdir(parents=True)
        node = bin_ / 'node'
        node.write_text('#!/bin/sh\necho v24.14.1\n')
        node.chmod(0o755)
        atalho = self.tmp / 'multishell-123' / 'node'
        atalho.parent.mkdir()
        atalho.symlink_to(node)
        self.assertEqual(instalar.node(self.pasta, procurar=lambda _n: str(atalho)), str(node))
        self.assertEqual((self.pasta / 'node.txt').read_text().strip(), str(node))
        self.assertIsNone(instalar.node(self.pasta, procurar=lambda _n: None))
        self.assertFalse((self.pasta / 'node.txt').exists())


class TestInstalarSh(unittest.TestCase):
    def _rodar(self, *args, pasta=CONVERSOR):
        return subprocess.run(['bash', str(pasta / 'instalar.sh'), *args], capture_output=True, text=True, timeout=60)

    def test_ajuda_e_opcao_desconhecida(self):
        r = self._rodar('--ajuda')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('--audio', r.stdout)
        self.assertIn('Uso: ./instalar.sh', r.stdout)
        self.assertNotIn('set -euo', r.stdout)
        r = self._rodar('--audi')
        self.assertEqual(r.returncode, 2)
        self.assertIn('Opção desconhecida: --audi', r.stdout)

    def test_atualizar_yt_dlp_sem_o_modo_de_audio(self):
        tmp = Path(tempfile.mkdtemp(prefix='central-teste-'))
        self.addCleanup(shutil.rmtree, tmp, True)
        shutil.copy(CONVERSOR / 'instalar.sh', tmp / 'instalar.sh')
        r = self._rodar('--atualizar-yt-dlp', pasta=tmp)
        self.assertEqual(r.returncode, 1)
        self.assertIn('rode ./instalar.sh --audio', r.stdout)
        self.assertEqual(sorted(os.listdir(tmp)), ['instalar.sh'])


if __name__ == '__main__':
    unittest.main()

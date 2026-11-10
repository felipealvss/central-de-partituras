"""Importação por link (partituras/audio/baixar.py) com um yt-dlp falso: nada sai para a internet.

O falso grava os argumentos que recebeu e se comporta conforme o fim da URL: ok (progresso, áudio e
info.json), erro, longo (recusado pelo filtro de duração), vazio (sai sem baixar) e mudo (trava calado).
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from pathlib import Path
from unittest import mock

from partituras.audio import baixar
from partituras.erros import ErroConversao

CONVERSOR = Path(__file__).resolve().parents[1]

YT_DLP_FALSO = textwrap.dedent('''\
    #!PYTHON
    import json, os, shutil, sys, time
    from pathlib import Path
    args = sys.argv[1:]
    Path(os.environ['FALSO_ARGS']).write_text(json.dumps(args))
    Path(os.environ['FALSO_ARGS'] + '.pid').write_text(str(os.getpid()))
    url = args[args.index('--') + 1]
    saida = args[args.index('-o') + 1]
    amostra = Path(os.environ['FALSO_AMOSTRA'])
    modo = url.rsplit('/', 1)[-1]
    if modo == 'erro':
        print('[youtube] abc: Downloading webpage', flush=True)
        print('ERROR: [youtube] abc: Private video. Sign in if you have access', flush=True)
        sys.exit(1)
    if modo == 'longo':
        print('[download] abc does not pass filter (duration <= 1800), skipping ..', flush=True)
        sys.exit(0)
    if modo == 'vazio':
        sys.exit(0)
    if modo == 'mudo':
        time.sleep(60)
        sys.exit(0)
    for p in (12.5, 50.0, 100.0):
        print(f'[download]  {p:5.1f}% of    1.00MiB at    1.00MiB/s ETA 00:00', flush=True)
    shutil.copyfile(amostra, saida.replace('%(ext)s', amostra.suffix[1:]))
    Path(saida.replace('%(ext)s', 'info.json')).write_text(json.dumps({'title': 'Vídeo de teste', 'duration': 2}))
    ''')


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'sem o ffmpeg')
class TestBaixar(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix='central-teste-'))
        cls.amostras = {}
        for ext, codec in (('webm', ['-c:a', 'libopus', '-b:a', '64k']), ('flac', ['-c:a', 'flac'])):
            arq = cls.tmp / f'amostra.{ext}'
            r = subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-f', 'lavfi', '-i', 'sine=frequency=440:duration=2',
                                *codec, str(arq)], capture_output=True, timeout=60)
            if r.returncode == 0:
                cls.amostras[ext] = arq
        cls.yt_dlp = cls.tmp / 'yt-dlp'
        cls.yt_dlp.write_text(YT_DLP_FALSO.replace('PYTHON', sys.executable))
        cls.yt_dlp.chmod(0o755)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        self.pasta = Path(tempfile.mkdtemp(prefix='central-teste-', dir=self.tmp))
        self.args = self.pasta.parent / f'{self.pasta.name}-args.json'
        self.eventos = []

    def _executar(self, fim, amostra='webm', timeout=1800, yt_dlp=None):
        if amostra not in self.amostras:
            self.skipTest(f'o ffmpeg daqui não gera {amostra}')
        tarefa = {'tipo': 'baixar', 'url': f'https://www.youtube.com/watch?v=abc&x=/{fim}', 'pasta_audio': str(self.pasta),
                  'yt_dlp': str(self.yt_dlp) if yt_dlp is None else yt_dlp, 'node': '/opt/node/bin/node'}
        with mock.patch.dict(os.environ, {'FALSO_ARGS': str(self.args), 'FALSO_AMOSTRA': str(self.amostras[amostra])}):
            return baixar.executar(tarefa, lambda *e: self.eventos.append(e), timeout=timeout)

    def test_comando_trava_o_link_e_as_regras(self):
        cmd = baixar.comando('/bin/yt-dlp', '/opt/node/bin/node', '--exec=rm', Path('/p'))
        self.assertEqual(cmd[-2:], ['--', '--exec=rm'])
        for opcao in ('--no-playlist', '--write-info-json', '--newline'):
            self.assertIn(opcao, cmd)
        self.assertEqual(cmd[cmd.index('--js-runtimes') + 1], 'node:/opt/node/bin/node')
        self.assertEqual(cmd[cmd.index('--match-filter') + 1], 'duration <= 1800')
        self.assertNotIn('--js-runtimes', baixar.comando('/bin/yt-dlp', None, 'https://x', Path('/p')))

    def test_baixa_com_progresso_titulo_e_aviso_de_perdas(self):
        (self.pasta / '.baixando.webm.part').write_bytes(b'resto da tentativa anterior')
        r = self._executar('ok')
        a = r['audio']
        self.assertTrue(r['ok'])
        self.assertEqual((a['arquivo'], a['titulo_original'], a['nome_original']),
                         ('original.webm', 'Vídeo de teste', 'Vídeo de teste.webm'))
        self.assertTrue(a['com_perdas'])
        self.assertIn('com perdas', a['aviso'])
        self.assertEqual(len(a['hash']), 16)
        self.assertEqual([e[2] for e in self.eventos], [None, 12, 50, 100])
        self.assertEqual(sorted(p.name for p in self.pasta.iterdir()), ['download.log', 'original.webm'])
        self.assertIn('100.0%', (self.pasta / 'download.log').read_text())
        args = json.loads(self.args.read_text())
        self.assertEqual(args[-2:], ['--', 'https://www.youtube.com/watch?v=abc&x=/ok'])

    def test_sem_perdas_nao_avisa(self):
        a = self._executar('ok', amostra='flac')['audio']
        self.assertFalse(a['com_perdas'])
        self.assertNotIn('aviso', a)
        self.assertEqual(a['arquivo'], 'original.flac')

    def test_erros_do_yt_dlp_explicados(self):
        with self.assertRaises(ErroConversao) as ctx:
            self._executar('erro')
        self.assertIn('Private video', str(ctx.exception))
        self.assertIn('--atualizar-yt-dlp', str(ctx.exception))
        with self.assertRaises(ErroConversao) as ctx:
            self._executar('longo')
        self.assertIn('mais de 30 minutos', str(ctx.exception))
        with self.assertRaises(ErroConversao):
            self._executar('vazio')
        with self.assertRaises(ErroConversao) as ctx:
            self._executar('ok', yt_dlp='')
        self.assertIn('instalar.sh --audio', str(ctx.exception))

    def test_tempo_limite_vale_mesmo_calado(self):
        inicio = time.monotonic()
        with self.assertRaises(ErroConversao) as ctx:
            self._executar('mudo', timeout=1)
        self.assertLess(time.monotonic() - inicio, 15)
        self.assertIn('tempo limite', str(ctx.exception))

    def test_pelo_trabalhador_so_sai_json(self):
        if 'webm' not in self.amostras:
            self.skipTest('sem libopus')
        tarefa = self.pasta.parent / f'{self.pasta.name}-tarefa.json'
        tarefa.write_text(json.dumps({'tipo': 'baixar', 'ambiente': 'audio', 'url': 'https://x.org/v/ok',
                                      'pasta_audio': str(self.pasta), 'yt_dlp': str(self.yt_dlp), 'node': None}))
        r = subprocess.run([sys.executable, '-m', 'partituras.audio.trabalho', str(tarefa)], capture_output=True,
                           text=True, cwd=CONVERSOR, timeout=120,
                           env={**os.environ, 'CENTRAL_PARTITURAS_RAIZ': str(self.tmp), 'FALSO_ARGS': str(self.args),
                                'FALSO_AMOSTRA': str(self.amostras['webm'])})
        eventos = [json.loads(x) for x in r.stdout.splitlines() if x.strip()]
        self.assertTrue(eventos[-1]['fim'] and eventos[-1]['ok'], r.stderr[-1500:])
        self.assertEqual(eventos[-1]['audio']['arquivo'], 'original.webm')
        self.assertIn(50, [e.get('i') for e in eventos])


if __name__ == '__main__':
    unittest.main()

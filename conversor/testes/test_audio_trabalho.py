"""Trabalhador de áudio e separação.

No Python do servidor: o núcleo da separação com um modelo falso (sem rede neural), a reserva por falta de memória
e a checagem estática do código vendorizado do modelo (lido como texto; nunca importado nos testes).
No ambiente de áudio: o trabalhador real com o cache de stems preenchido a partir do piloto (a separação real
não roda nos testes: quem a executa é a Central, iniciada pelo usuário).
"""
import ast
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

from partituras.audio import mega53, separar
from testes.util import DADOS

PACOTE = Path(__file__).resolve().parents[1] / 'partituras' / 'audio'
AUDIO = DADOS / 'audio'


class TestSepararArray(unittest.TestCase):
    def test_modelo_identidade_reconstroi_a_entrada(self):
        rng = np.random.default_rng(0)
        audio = rng.standard_normal((2, 1737)).astype(np.float32)
        for segundos in (0.13, 0.3, 1.0, 5.0):
            with self.subTest(segundos=segundos):
                saida = separar.separar_array(audio, lambda x: np.stack([x, 2 * x]), 2, segundos, sr=1000)
                self.assertEqual(saida.shape, (2, 2, 1737))
                np.testing.assert_allclose(saida[0], audio, atol=1e-5)
                np.testing.assert_allclose(saida[1], 2 * audio, atol=1e-5)

    def test_falta_de_memoria_diminui_o_trecho_e_depois_usa_o_processador(self):
        class SemMemoria(Exception):
            pass
        liberou = []

        def gpu_pequena(x):
            if x.shape[1] > 500:  # só cabem trechos de até 0,5 s (sr=1000)
                raise SemMemoria
            return np.stack([x])

        audio = np.ones((2, 3000), dtype=np.float32)
        modelos = iter([('cuda', gpu_pequena, lambda: liberou.append(1)), ('cpu', lambda x: np.stack([x]), lambda: None)])
        _, disp, s = self._reserva(audio, modelos, 2.0, SemMemoria)
        self.assertEqual(disp, 'cuda')
        self.assertLessEqual(s * 1000, 500)
        self.assertGreaterEqual(len(liberou), 1)

        def gpu_sem_memoria(_x):
            raise SemMemoria
        modelos = iter([('cuda', gpu_sem_memoria, lambda: None), ('cpu', lambda x: np.stack([x]), lambda: None)])
        saida, disp, _ = self._reserva(audio, modelos, 2.0, SemMemoria)
        self.assertEqual(disp, 'cpu')
        np.testing.assert_allclose(saida[0], audio, atol=1e-5)

    def _reserva(self, audio, modelos, segundos, erro):
        original = separar.separar_array
        separar.separar_array = lambda a, m, n, s, p=None: original(a, m, n, s, p, sr=1000)
        try:
            return separar.separar_com_reserva(audio, modelos, 1, segundos, (erro,), minimo=0.2)
        finally:
            separar.separar_array = original

    def test_cache_incompleto_nao_vale(self):
        tmp = Path(tempfile.mkdtemp(prefix='central-teste-'))
        self.addCleanup(shutil.rmtree, tmp, True)
        destino = tmp / mega53.VERSAO
        destino.mkdir()
        (destino / 'separacao.json').write_text(json.dumps({'modelo': mega53.VERSAO}))
        (destino / 'saxophone.flac').write_bytes(b'x')
        self.assertIsNone(separar.cache_valido(destino, ('saxophone', 'vocal')))
        (destino / 'vocal.flac').write_bytes(b'x')
        self.assertIsNotNone(separar.cache_valido(destino, ('saxophone', 'vocal')))
        (tmp / '.temp-abc').mkdir()
        separar.limpar_temporarios(tmp)
        self.assertFalse((tmp / '.temp-abc').exists())


class TestCodigoVendorizado(unittest.TestCase):
    """O código do modelo é de terceiros: só pode definir a rede. Lido como texto (ast), nunca executado aqui."""
    HASHES = {'bs_roformer.py': 'f6471bba1c03be2c571f27b237136b201c7aab12ff10043d675b83e1e162c1d8',
              'attend.py': '0459d799ade55541df2994b0becf7aec12214491360c5a06e346f6d615eaed15'}
    PERMITIDOS = {'functools', 'collections', 'packaging', 'os', 'torch', 'torch.nn', 'torch.nn.functional',
                  'torch.utils.checkpoint', 'beartype', 'beartype.typing', 'rotary_embedding_torch', 'einops',
                  'einops.layers.torch', 'PoPE_pytorch', 'attend'}
    PROIBIDOS = {'eval', 'exec', 'compile', 'open', '__import__', 'system', 'popen', 'Popen', 'urlopen', 'socket',
                 'remove', 'unlink', 'rmtree', 'load', 'save', 'getattr', 'setattr', 'globals', 'locals'}

    def test_hash_importacoes_e_chamadas(self):
        for nome, esperado in self.HASHES.items():
            with self.subTest(nome):
                texto = (PACOTE / 'bs_roformer' / nome).read_bytes()
                self.assertEqual(hashlib.sha256(texto).hexdigest(), esperado, 'o código vendorizado mudou: revise')
                arvore = ast.parse(texto)
                for no in ast.walk(arvore):
                    if isinstance(no, ast.Import):
                        for a in no.names:
                            self.assertIn(a.name, self.PERMITIDOS)
                    elif isinstance(no, ast.ImportFrom):
                        self.assertIn(no.module, self.PERMITIDOS)
                    elif isinstance(no, ast.Call):
                        alvo = no.func.attr if isinstance(no.func, ast.Attribute) else getattr(no.func, 'id', '')
                        self.assertNotIn(alvo, self.PROIBIDOS, f'{nome}:{no.lineno}')
        self.assertTrue((PACOTE / 'bs_roformer' / 'LICENSE').read_text().count('MIT License') == 2)


try:
    import librosa  # noqa: F401
    import music21  # noqa: F401
    AMBIENTE_AUDIO = True
except ImportError:
    AMBIENTE_AUDIO = False


@unittest.skipUnless(AMBIENTE_AUDIO and (AUDIO / 'saxophone.flac').exists(), 'ambiente de áudio ou dados do piloto ausentes')
class TestTrabalhadorReal(unittest.TestCase):
    """Trabalhador real com o cache de stems preenchido a partir do piloto (sem rodar a separação)."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix='central-teste-'))
        audio = cls.tmp / 'musicas' / 'faixa' / 'audio'
        cache = audio / 'separacao' / mega53.VERSAO
        cache.mkdir(parents=True)
        shutil.copyfile(AUDIO / 'mistura.flac', audio / 'original.flac')
        shutil.copyfile(AUDIO / 'mistura.flac', audio / 'mistura.flac')
        for stem in ('saxophone', 'trumpet', 'trombone', 'vocal'):
            shutil.copyfile(AUDIO / f'{stem}.flac', cache / f'{stem}.flac')
        (cache / 'separacao.json').write_text(json.dumps({
            'modelo': mega53.VERSAO, 'dispositivo': 'cuda', 'trecho_s': 2.0, 'segundos': 934.0,
            'presenca': {'saxophone': 0.155, 'trumpet': 0.0, 'trombone': 0.0, 'vocal': 0.49}}))
        cls.audio = audio
        cls.conv = cls.tmp / 'musicas' / 'faixa' / 'conversoes' / 'c1'
        cls.conv.mkdir(parents=True)
        cls.saida = cls.tmp / 'partituras'

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def _tarefa(self, tipo, instrumento='sax-tenor', ajustes=None, conv=None):
        return {'tipo': tipo, 'ambiente': 'audio', 'conv': str(conv or self.conv), 'pasta_audio': str(self.audio),
                'audio': {'original': str(self.audio / 'original.flac')},
                'musica': {'id': 'faixa', 'titulo': 'Faixa do piloto', 'compositor': None},
                'instrumento': instrumento, 'ajustes': ajustes or {}, 'opcoes': {'pdf': True},
                'saida': {'pasta': str(self.saida), 'nome': 'Faixa do piloto - Sax tenor'}, 'substituir': False}

    def test_1_converter_usa_o_cache_e_publica(self):
        from partituras.audio import trabalho
        r = trabalho.executar(self._tarefa('converter'))
        self.assertTrue(r['ok'])
        self.assertEqual((r['versao'], r['resumo']['trechos'], r['conversao']['separacao']['cache']), (1, 11, True))
        self.assertAlmostEqual(r['resumo']['notas'], 192, delta=2)
        v = Path(r['pasta_versao'])
        for nome in ('partitura.musicxml', 'partitura.mscz', 'partitura.pdf', 'sintese.flac', 'trecho-01.png',
                     'conferencia.json', 'versao.json', 'notas.json'):
            self.assertTrue((v / nome).is_file(), nome)
        self.assertEqual(sorted(Path(p).name for p in r['publicados'].values()),
                         ['Faixa do piloto - Sax tenor.mscz', 'Faixa do piloto - Sax tenor.pdf'])

    def test_2_acabar_com_ajustes_reaproveita_a_analise(self):
        from partituras.audio import trabalho
        r = trabalho.executar(self._tarefa('acabar', ajustes={'trechos': {'1': False}}))
        self.assertTrue(r['ok'])
        self.assertLess(r['resumo']['notas'], 150)

    def test_3_instrumento_ausente_explica(self):
        from partituras.audio import trabalho
        from partituras.erros import ErroConversao
        conv = self.tmp / 'musicas' / 'faixa' / 'conversoes' / 'c2'
        conv.mkdir()
        with self.assertRaises(ErroConversao) as ctx:
            trabalho.executar(self._tarefa('converter', instrumento='trompete', conv=conv))
        self.assertIn('saxophone 16%', str(ctx.exception))

    def test_4_subprocesso_so_emite_json(self):
        arq = self.tmp / 'tarefa.json'
        arq.write_text(json.dumps(self._tarefa('acabar', ajustes={'compasso': 3})))
        r = subprocess.run([sys.executable, '-m', 'partituras.audio.trabalho', str(arq)], capture_output=True,
                           text=True, cwd=PACOTE.parents[1], timeout=600,
                           env={**os.environ, 'CENTRAL_PARTITURAS_RAIZ': str(self.tmp)})
        linhas = [x for x in r.stdout.splitlines() if x.strip()]
        eventos = [json.loads(x) for x in linhas]  # nenhuma linha fora do formato
        self.assertTrue(eventos[-1]['fim'] and eventos[-1]['ok'], r.stderr[-2000:])
        self.assertEqual(eventos[-1]['resumo']['compasso'], '3/4')


if __name__ == '__main__':
    unittest.main()

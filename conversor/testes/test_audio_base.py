"""Base do modo de áudio: tabela de instrumentos, ajustes, leitura de arquivos e a regra de importação
(os módulos leves não podem puxar dependências pesadas, porque rodam no Python do servidor)."""
import os
import shutil
import subprocess
import sys
import unittest
import wave
from pathlib import Path
from unittest import mock

from partituras import musescore
from partituras.audio import fonte, instrumentos
from partituras.erros import ErroConversao
from testes.util import temporaria

CONVERSOR = Path(__file__).resolve().parents[1]


class TestInstrumentos(unittest.TestCase):
    def test_nomes_de_nota(self):
        self.assertEqual([instrumentos.midi(n) for n in ('C4', 'Bb3', 'F#6', 'G2', 'A1', 'B♭3')],
                         [60, 58, 90, 43, 33, 58])

    def test_tabela_coerente(self):
        for iid, i in instrumentos.INSTRUMENTOS.items():
            with self.subTest(iid):
                self.assertIn(i['stem'], instrumentos.STEMS)
                baixo, alto = (instrumentos.midi(n) for n in i['busca'])
                self.assertLess(baixo, alto)
                diat, crom = i['transposicao']
                self.assertTrue(diat <= 0 and crom <= 0 and (diat == 0) == (crom == 0))
                # a busca (som real) cobre a extensão escrita transposta para som real
                self.assertLessEqual(baixo, i['extensao_escrita'][0] + crom)
                self.assertGreaterEqual(alto, i['extensao_escrita'][1] + crom)
        self.assertEqual(instrumentos.PADRAO, 'sax-tenor')
        self.assertEqual(instrumentos.obter('sax-tenor')['busca'], ('G2', 'C6'))  # a faixa do piloto
        self.assertEqual(instrumentos.STEMS, ('saxophone', 'trombone', 'trumpet', 'vocal'))
        with self.assertRaises(ValueError):
            instrumentos.obter('kazoo')

    def test_ajustes(self):
        self.assertEqual(instrumentos.validar_ajustes(None), {'trechos': {}})
        self.assertEqual(instrumentos.validar_ajustes({'trechos': {'2': False, 3: 1}, 'compasso': '3', 'rotacao': 2,
                                                       'andamento': 'dobro', 'grade': 2}),
                         {'trechos': {'2': False, '3': True}, 'compasso': 3, 'rotacao': 2, 'andamento': 'dobro',
                          'grade': 2})
        for ruim in ({'compasso': 7}, {'compasso': 3, 'rotacao': 3}, {'andamento': 'rápido'}, {'grade': 3},
                     {'trechos': {'x': True}}, {'trechos': [1]}, 'texto'):
            with self.assertRaises(ValueError, msg=ruim):
                instrumentos.validar_ajustes(ruim)


class TestFonte(unittest.TestCase):
    def setUp(self):
        self.tmp = temporaria(self)

    def _wav(self, nome='a.wav', segundos=0.5, taxa=22050):
        p = self.tmp / nome
        with wave.open(str(p), 'wb') as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(taxa)
            w.writeframes(b'\x00\x00' * int(segundos * taxa))
        return p

    def test_extensoes_e_identidade(self):
        self.assertTrue(fonte.e_audio('Música.MP3'))
        self.assertFalse(fonte.e_audio('foto.heic'))
        a, b = self._wav('a.wav'), self._wav('b.wav')
        self.assertEqual(fonte.identificar(a), fonte.identificar(b))
        self.assertEqual(len(fonte.identificar(a)), 16)

    @unittest.skipUnless(shutil.which('ffprobe'), 'sem ffprobe')
    def test_sondar(self):
        info = fonte.sondar(self._wav())
        self.assertEqual((info['codec'], info['taxa'], info['canais'], info['com_perdas']), ('pcm_s16le', 22050, 1, False))
        self.assertAlmostEqual(info['duracao'], 0.5, places=1)
        falso = self.tmp / 'falso.mp3'
        falso.write_bytes(b'nada de audio aqui')
        with self.assertRaises(ErroConversao):
            fonte.sondar(falso)


class TestMuseScoreEstilo(unittest.TestCase):
    def test_estilo_vira_opcao_S(self):
        tmp = temporaria(self)
        destino = tmp / 'x.pdf'
        chamadas = []

        def rodar(cmd, **_):
            chamadas.append([str(c) for c in cmd])
            destino.write_bytes(b'%PDF')
        with mock.patch('partituras.musescore.rodar', side_effect=rodar), \
                mock.patch('partituras.musescore._mscore', return_value='mscore'):
            musescore.converter(tmp / 'x.mscz', destino, estilo=tmp / 'e.mss')
            musescore.converter(tmp / 'x.mscz', destino)
        self.assertEqual(chamadas[0][1:3], ['-S', str(tmp / 'e.mss')])
        self.assertNotIn('-S', chamadas[1])


class TestGuardaDeImportacao(unittest.TestCase):
    """Os módulos leves do áudio não podem importar nada pesado (rodam no servidor, sem torch nem librosa)."""

    def test_modulos_leves_sem_dependencias_pesadas(self):
        bloqueio = (
            "import sys\n"
            "PESADOS = {'PIL', 'pillow_heif', 'numpy', 'flask', 'waitress', 'homr', 'torch', 'librosa', 'music21',\n"
            "           'soundfile', 'soxr', 'matplotlib', 'scipy'}\n"
            "class Bloqueio:\n"
            "    def find_spec(self, nome, caminho=None, alvo=None):\n"
            "        if nome.split('.')[0] in PESADOS:\n"
            "            raise ImportError('pesado: ' + nome)\n"
            "sys.meta_path.insert(0, Bloqueio())\n"
            "import partituras.audio.instrumentos, partituras.audio.fonte, partituras.audio.disponivel\n"
            "print('ok')\n")
        r = subprocess.run([sys.executable, '-c', bloqueio], cwd=CONVERSOR, capture_output=True, text=True,
                           env={**os.environ, 'PYTHONPATH': str(CONVERSOR)})
        self.assertEqual(r.stdout.strip(), 'ok', r.stderr)


if __name__ == '__main__':
    unittest.main()

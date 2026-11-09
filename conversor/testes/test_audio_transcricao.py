"""Transcrição da linha isolada (roda no ambiente de áudio; no Python do servidor estes testes são pulados).

Referência: a faixa do piloto (sax tenor numa gravação comercial), que o usuário ouviu e avaliou como quase perfeito. Os stems e
as notas do piloto ficam em testes/dados/audio/ (fora do repositório: derivam de uma gravação protegida).
"""
import json
import shutil
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

try:
    import librosa  # noqa: F401
    import music21  # noqa: F401
    import soundfile  # noqa: F401
except ImportError:
    raise unittest.SkipTest('ambiente de áudio ausente (rode estes testes com conversor/.venv-audio)')

from partituras import caminhos
from partituras.audio import instrumentos, partitura, transcricao
from testes.util import DADOS, temporaria

AUDIO = DADOS / 'audio'
BATIDAS = caminhos.MODELOS_AUDIO / 'beat_this-final0.ckpt'


def _xml(caminho):
    return ET.parse(caminho).getroot()


class TestReferenciaDoPiloto(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not (AUDIO / 'saxophone.flac').exists() or not BATIDAS.exists():
            raise unittest.SkipTest('sem os dados do piloto ou o modelo de pulsação')
        cls.tmp = Path(tempfile.mkdtemp(prefix='central-teste-'))
        transcricao.analisar(AUDIO / 'mistura.flac', AUDIO / 'saxophone.flac', AUDIO / 'vocal.flac', 'sax-tenor',
                             cls.tmp / 'analise', BATIDAS)
        cls.analise, cls.curvas = transcricao.carregar_analise(cls.tmp / 'analise')  # ida e volta pelo disco
        cls.res = transcricao.gerar(cls.analise, cls.curvas, AUDIO / 'saxophone.flac', cls.tmp / 'v1', {},
                                    'Faixa do piloto', musescore=False)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_trechos_pulsacao_e_tom(self):
        rel = self.res['conferencia']
        self.assertEqual(len(rel['trechos']), 11)
        self.assertAlmostEqual(rel['bpm'], 111.1, delta=0.5)
        self.assertEqual((rel['compasso'], rel['tom_som'], rel['tom_escrito']), ('4/4', 'Si maior', 'Ré♭ maior'))
        self.assertLess(rel['fora_dos_trechos_db'], -20)

    def test_notas_iguais_ao_piloto(self):
        piloto = json.loads((AUDIO / 'piloto-notas.json').read_text())
        ref = {(n['nota'], n['b0'], n['b1']) for n in piloto}
        novas = {(n['nota'], n['b0'], n['b1']) for n in self.res['notas']}
        self.assertLessEqual(abs(len(novas) - len(ref)), 2)
        self.assertGreaterEqual(len(ref & novas) / len(ref), 0.98)

    def test_parte_de_sax_tenor(self):
        raiz = _xml(self.tmp / 'v1' / 'partitura.musicxml')
        self.assertEqual(raiz.findtext('.//key/fifths'), '-5')
        self.assertEqual(raiz.findtext('.//transpose/chromatic'), '-2')  # nona maior = oitava + 2ª maior
        self.assertEqual(raiz.findtext('.//transpose/octave-change'), '-1')
        self.assertEqual(raiz.findtext('.//instrument-sound'), 'wind.reed.saxophone.tenor')
        self.assertEqual(raiz.findtext('.//part-name'), 'Sax tenor')
        self.assertTrue((self.tmp / 'v1' / 'sintese.flac').exists())
        self.assertEqual(len(list((self.tmp / 'v1').glob('trecho-*.png'))), 11)

    def test_ajustes_refazem_so_a_partitura(self):
        sem_1 = transcricao.gerar(self.analise, self.curvas, AUDIO / 'saxophone.flac', self.tmp / 'v2',
                                  {'trechos': {'1': False}}, 'Faixa do piloto', musescore=False)
        self.assertLess(sem_1['conferencia']['notas'], self.res['conferencia']['notas'])
        self.assertFalse(sem_1['conferencia']['trechos'][0]['incluido'])
        dobro = transcricao.gerar(self.analise, self.curvas, AUDIO / 'saxophone.flac', self.tmp / 'v3',
                                  {'andamento': 'dobro'}, 'Faixa do piloto', musescore=False)
        self.assertAlmostEqual(dobro['conferencia']['bpm'], 2 * self.res['conferencia']['bpm'], delta=2)
        tres = transcricao.gerar(self.analise, self.curvas, AUDIO / 'saxophone.flac', self.tmp / 'v4',
                                 {'compasso': 3}, 'Faixa do piloto', musescore=False)
        self.assertEqual(tres['conferencia']['compasso'], '3/4')
        self.assertGreater(tres['conferencia']['total'], self.res['conferencia']['total'])

    @unittest.skipUnless(shutil.which('mscore'), 'sem MuseScore')
    def test_musescore_le_a_parte(self):
        r = transcricao.gerar(self.analise, self.curvas, AUDIO / 'saxophone.flac', self.tmp / 'v5', {}, 'Faixa do piloto')
        self.assertTrue(r['arquivos']['.mscz'].exists() and r['arquivos']['.pdf'].exists())


class TestNotacaoPorInstrumento(unittest.TestCase):
    """Uma frase em Si maior (som real) escrita para cada instrumento."""

    def _parte(self, iid):
        tmp = temporaria(self)
        notas = [{'nota': m, 'b0': i, 'b1': i + 1} for i, m in enumerate((59, 61, 63, 64, 66, 68, 70, 71))]
        info = partitura.escrever(notas, instrumentos.obter(iid), 4, 100, 0, 'Teste', None,
                                  tmp / 'som.musicxml', tmp / 'parte.musicxml')
        return _xml(tmp / 'parte.musicxml'), info

    def test_armaduras_e_claves(self):
        # (a frase é ambígua entre Si maior e Sol♯ menor; o que importa aqui é a armadura escrita)
        esperado = {'sax-tenor': ('-5', 'G'), 'sax-alto': ('-4', 'G'), 'sax-soprano': ('-5', 'G'),
                    'trompete': ('-5', 'G'), 'trombone': ('5', 'F')}
        for iid, (fifths, sinal) in esperado.items():
            with self.subTest(iid):
                raiz, _ = self._parte(iid)
                self.assertEqual(raiz.findtext('.//key/fifths'), fifths)
                self.assertEqual(raiz.findtext('.//clef/sign'), sinal)
                self.assertEqual(raiz.findtext('.//instrument-sound'), instrumentos.obter(iid)['som'])

    def test_aviso_de_extensao(self):
        tmp = temporaria(self)
        notas = [{'nota': 80, 'b0': 0, 'b1': 1}, {'nota': 40, 'b0': 1, 'b1': 2}]  # Sol♯5 e Mi2 em som real
        info = partitura.escrever(notas, instrumentos.obter('sax-tenor'), 4, 100, 0, 'T', None,
                                  tmp / 's.musicxml', tmp / 'p.musicxml')
        self.assertEqual([f['acima'] for f in info['fora_extensao']], [True, False])  # Si♭6 e Fá♯3 escritos

    def test_anacruse_nao_some(self):
        notas = [{'nota': 60, 'b0': 1.0, 'b1': 2.0}, {'nota': 62, 'b0': 4.0, 'b1': 5.0}]
        self.assertEqual(partitura.inicio_dos_compassos(notas, 4, 3), -1)  # 1º tempo forte detectado na batida 3
        self.assertEqual(partitura.inicio_dos_compassos(notas, 4, 0), 0)


if __name__ == '__main__':
    unittest.main()

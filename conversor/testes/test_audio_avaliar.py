"""Avaliador contra gabarito (partituras/audio/avaliar.py), com partituras de sax tenor montadas no teste e,
se houver, a partitura do piloto. Ambiente de áudio (music21 e mir_eval)."""
import json
import shutil
import tempfile
import unittest
from pathlib import Path

try:
    import mir_eval  # noqa: F401
    import music21
    from partituras.audio import avaliar
    AMBIENTE_AUDIO = True
except ImportError:
    AMBIENTE_AUDIO = False

from testes.util import DADOS

# (início em tempos, duração, nota MIDI em som real): uma frase com nota que atravessa a barra e notas repetidas,
# 8 tempos de pausa, e uma segunda frase
FRASE_1 = [(0, 1, 63), (1, 0.5, 65), (1.5, 0.5, 66), (2, 1, 68), (3, 2, 70), (5, 1, 68), (6, 1, 68), (7, 1, 66)]
FRASE_2 = [(16, 1, 61), (17, 1, 63), (18, 2, 65), (20, 1, 63), (21, 1, 61)]


@unittest.skipUnless(AMBIENTE_AUDIO, 'sem o ambiente de áudio (music21, mir_eval)')
class TestAvaliar(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='central-teste-'))
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def partitura(self, notas, nome):
        """Parte de sax tenor escrita (transposta, com ligaduras nas barras), como a Central e o MuseScore gravam."""
        p = music21.stream.Part()
        p.insert(0, music21.instrument.TenorSaxophone())
        p.insert(0, music21.meter.TimeSignature('4/4'))
        for ini, dur, nota in notas:
            n = music21.note.Note(nota)
            n.quarterLength = dur
            p.insert(ini, n)
        p = p.makeNotation()  # compassos, pausas e ligaduras nas barras
        p.atSoundingPitch = True
        s = music21.stream.Score([p.toWrittenPitch()])
        destino = self.tmp / f'{nome}.musicxml'
        s.write('musicxml', fp=str(destino))
        return destino

    def medir(self, ref, est, **kw):
        return avaliar.avaliar(avaliar.notas_da_partitura(self.partitura(ref, 'ref')),
                               avaliar.notas_da_partitura(self.partitura(est, 'est')), **kw)

    def test_leitura_volta_ao_som_real_e_junta_as_ligaduras(self):
        notas = avaliar.notas_da_partitura(self.partitura(FRASE_1, 'f'))
        self.assertEqual([(n['ini'], n['fim'] - n['ini'], n['nota']) for n in notas], FRASE_1)
        self.assertEqual(len(avaliar.frases(avaliar.notas_da_partitura(self.partitura(FRASE_1 + FRASE_2, 'g')))), 2)

    def test_igual_da_tudo_certo(self):
        r = self.medir(FRASE_1 + FRASE_2, FRASE_1 + FRASE_2)
        self.assertEqual((r['f1_ataque_altura'], r['f1_ataque_fim'], r['ligaduras_indevidas'],
                          r['ligaduras_faltantes'], r['deslocamento_geral']), (1.0, 1.0, 0, 0, 0.0))

    def test_nota_errada(self):
        est = list(FRASE_1)
        est[3] = (2, 1, 69)
        r = self.medir(FRASE_1, est)
        self.assertAlmostEqual(r['precisao'], 7 / 8, places=3)
        self.assertAlmostEqual(r['revocacao'], 7 / 8, places=3)

    def test_ligadura_indevida_e_faltante(self):
        juntas = [n for n in FRASE_1 if n[0] not in (5, 6)] + [(5, 2, 68)]       # as duas Lá♭ repetidas viram uma
        r = self.medir(FRASE_1, sorted(juntas))
        self.assertEqual((r['ligaduras_indevidas'], r['ligaduras_faltantes']), (1, 0))
        separada = [n for n in FRASE_1 if n[0] != 3] + [(3, 1, 70), (4, 1, 70)]  # a nota longa atacada de novo
        r = self.medir(FRASE_1, sorted(separada))
        self.assertEqual((r['ligaduras_indevidas'], r['ligaduras_faltantes']), (0, 1))

    def test_alinha_deslocamento_geral_e_por_frase(self):
        um_tempo_depois = [(i + 1, d, n) for i, d, n in FRASE_1 + FRASE_2]
        r = self.medir(FRASE_1 + FRASE_2, um_tempo_depois)
        self.assertEqual((r['f1_ataque_altura'], r['deslocamento_geral']), (1.0, -1.0))
        so_a_segunda = FRASE_1 + [(i + 0.5, d, n) for i, d, n in FRASE_2]
        r = self.medir(FRASE_1 + FRASE_2, so_a_segunda)
        self.assertEqual(r['f1_ataque_altura'], 1.0)
        self.assertEqual([f['deslocamento'] for f in r['frases']], [0.0, -0.5])

    def test_nota_a_mais_fora_das_frases(self):
        r = self.medir(FRASE_1, FRASE_1 + [(30, 1, 60)])
        self.assertEqual(r['notas_fora_das_frases'], 1)
        self.assertAlmostEqual(r['precisao'], 8 / 9, places=3)
        self.assertEqual(r['revocacao'], 1.0)

    def test_linha_de_comando_grava_json(self):
        saida = self.tmp / 'r.json'
        avaliar.main([str(self.partitura(FRASE_1, 'a')), str(self.partitura(FRASE_1, 'b')), '--json', str(saida)])
        self.assertEqual(json.loads(saida.read_text())['f1_ataque_altura'], 1.0)


@unittest.skipUnless(AMBIENTE_AUDIO and (DADOS / 'audio' / 'piloto-partitura-tenor.musicxml').exists(),
                     'sem o ambiente de áudio ou a partitura do piloto')
class TestPartituraDoPiloto(unittest.TestCase):
    def test_partitura_do_piloto_contra_ela_mesma_transposta_para_o_som_real(self):
        piloto = avaliar.notas_da_partitura(DADOS / 'audio' / 'piloto-partitura-tenor.musicxml')
        self.assertEqual(len(piloto), 192)
        self.assertTrue(all(43 <= n['nota'] <= 84 for n in piloto))  # som real do tenor (Sol2–Dó6)
        r = avaliar.avaliar(piloto, piloto)
        self.assertEqual(r['f1_ataque_altura'], 1.0)


if __name__ == '__main__':
    unittest.main()

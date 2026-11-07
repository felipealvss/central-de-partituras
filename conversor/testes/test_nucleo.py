import os
import re
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from partituras import conferencia
from partituras import musicxml as mx
from partituras import notacao, processos, publicar
from partituras.erros import ErroConversao
from testes.util import DADOS, RAIZ_PROJETO, homr_unido


def _referencia(nome):
    texto = (DADOS / nome).read_text(encoding='utf-8')
    pausas = re.search(r'\n  (c\.\d+: \d+(?:, c\.\d+: \d+)*)\n', texto).group(1)
    so_pausa = texto.split('Compassos só com pausa')[1].splitlines()[1].strip()
    return pausas, so_pausa


class TestConferencia(unittest.TestCase):
    """O relatório novo tem de encontrar o mesmo que o relatório de referência (código anterior)."""

    def _comparar(self, arvore, referencia, motor):
        mx.normalizar_multirests(arvore)
        mx.ajustar(arvore, 'X', 'Y', None)
        rel = conferencia.analisar(arvore, motor)
        pausas, so_pausa = _referencia(referencia)
        self.assertEqual(', '.join(f"c.{p['n']}: {p['lido']}" for p in rel['pausas_longas']), pausas)
        self.assertEqual(', '.join(map(str, rel['so_pausa'])), so_pausa)
        return rel

    def test_homr_igual_a_referencia(self):
        rel = self._comparar(homr_unido(), 'referencia-homr.txt', 'homr')
        self.assertEqual(rel['total'], 93)
        self.assertEqual(rel['duracao_errada'], [])

    def test_audiveris_igual_a_referencia(self):
        rel = self._comparar(mx.ler(DADOS / 'audiveris.mxl'), 'referencia-audiveris.txt', 'audiveris')
        self.assertEqual(rel['total'], 76)
        self.assertEqual([(c['n'], c['tempos']) for c in rel['duracao_errada']], [(54, 3)])
        self.assertTrue(rel['suspeitos'])

    def test_total_esperado_e_alertas(self):
        t = homr_unido()
        mx.normalizar_multirests(t)
        rel = conferencia.analisar(t, 'homr', 165)
        self.assertEqual(rel['diferenca'], -72)
        self.assertTrue(rel['alertas'])
        self.assertIn('faltam 72', conferencia.formatar(rel))


class TestPublicar(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.origem = self.tmp / 'origem.mscz'
        self.origem.write_bytes(b'novo')

    def test_nunca_sobrescreve(self):
        pasta = self.tmp / 'saída com acentos'
        pasta.mkdir()
        (pasta / 'Hino.mscz').write_bytes(b'editado no MuseScore')
        feitos = publicar.publicar({'.mscz': self.origem}, pasta, 'Hino')
        self.assertEqual(feitos['.mscz'].name, 'Hino (2).mscz')
        self.assertEqual((pasta / 'Hino.mscz').read_bytes(), b'editado no MuseScore')

    def test_mesmo_nome_para_todos_os_arquivos(self):
        (self.tmp / 'Hino.pdf').write_bytes(b'x')
        pdf = self.tmp / 'o.pdf'
        pdf.write_bytes(b'p')
        feitos = publicar.publicar({'.mscz': self.origem, '.pdf': pdf}, self.tmp, 'Hino')
        self.assertEqual({p.name for p in feitos.values()}, {'Hino (2).mscz', 'Hino (2).pdf'})

    def test_pendrive_sem_links(self):
        with mock.patch('partituras.publicar.os.link', side_effect=OSError('sem links')):
            feitos = publicar.publicar({'.mscz': self.origem}, self.tmp, 'Hino')
            self.assertEqual(feitos['.mscz'].read_bytes(), b'novo')
            with self.assertRaises(FileExistsError):
                publicar.copiar_exclusivo(self.origem, feitos['.mscz'])

    def test_nome_seguro(self):
        self.assertEqual(publicar.nome_seguro('Grandioso És Tu: 1/2?'), 'Grandioso És Tu 1 2')
        self.assertEqual(publicar.nome_seguro('  '), 'Partitura')


class TestProcessos(unittest.TestCase):
    def test_limite_de_tempo(self):
        inicio = time.monotonic()
        with self.assertRaises(ErroConversao):
            processos.rodar(['sleep', '30'], timeout=1)
        self.assertLess(time.monotonic() - inicio, 10)

    def test_cancelar_mata_processo_neto(self):
        tmp = Path(tempfile.mkdtemp())
        pidfile = tmp / 'neto.pid'
        p = subprocess.Popen(['sh', '-c', f'sleep 60 & echo $! > {pidfile}; wait'], start_new_session=True)
        for _ in range(50):
            if pidfile.exists() and pidfile.read_text().strip():
                break
            time.sleep(0.1)
        neto = int(pidfile.read_text())
        processos.encerrar_grupo(p, espera=3)
        time.sleep(0.2)
        with self.assertRaises(ProcessLookupError):
            os.kill(neto, 0)


class TestNotacao(unittest.TestCase):
    def test_transcricao_de_my_savior_identica(self):
        arquivo = RAIZ_PROJETO / 'musicas' / 'my-savior-and-my-son' / 'transcricao' / 'transcricao.py'
        if not arquivo.exists():
            self.skipTest('transcrição de My Savior não está na pasta musicas/')
        p = notacao.carregar_transcricao(arquivo)
        self.assertEqual(p.musicxml(), (DADOS / 'revisada.musicxml').read_text(encoding='utf-8'))

    def test_duracao_errada_e_apontada(self):
        p = notacao.Partitura('X')
        p.c(1, ('C3', 'h', {}), arm=0)
        with self.assertRaises(ValueError):
            p.musicxml()

    def test_semicolcheia_exige_divisoes(self):
        p = notacao.Partitura('X')
        p.c(1, ('C3', 's', {}), arm=0)
        with self.assertRaises(ValueError):
            p.musicxml()
        p4 = notacao.Partitura('X', divisoes=4)
        p4.c(1, *[('C3', 's', {})] * 16, arm=0)
        self.assertIn('<divisions>4</divisions>', p4.musicxml())


if __name__ == '__main__':
    unittest.main()

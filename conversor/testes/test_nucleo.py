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
from partituras import imagens, revisao
from partituras.erros import Cancelado, ErroConversao
from PIL import Image
from testes.util import dado, homr_unido, temporaria


def _referencia(nome):
    texto = dado(nome).read_text(encoding='utf-8')
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
        rel = self._comparar(mx.ler(dado('audiveris.mxl')), 'referencia-audiveris.txt', 'audiveris')
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
        self.tmp = temporaria(self)
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
        tmp = temporaria(self)
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
    def test_transcricao_revisada_identica(self):
        p = notacao.carregar_transcricao(dado('transcricao-revisada.py'))
        self.assertEqual(p.musicxml(), dado('revisada.musicxml').read_text(encoding='utf-8'))

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


class TestImagens(unittest.TestCase):
    def test_audiveris_nunca_recebe_pagina_grande_demais(self):
        # Foto de celular de 37 MP: o Audiveris recusa páginas acima de 20 milhões de pixels.
        for largura, altura, inter in [(4592, 7223, 40), (4592, 7223, 24), (3000, 4000, 20)]:
            f = imagens.fator_audiveris(largura, altura, inter)
            self.assertLessEqual(largura * altura * f * f, imagens.PIXELS_MAX_AUDIVERIS * 1.0001)
        self.assertAlmostEqual(imagens.fator_audiveris(1500, 2000, 16), 2.0)  # pequena: amplia até a interlinha alvo
        self.assertEqual(imagens.fator_audiveris(2000, 3000, 40), 1.0)


class TestPacoteDeRevisao(unittest.TestCase):
    def setUp(self):
        self.tmp = temporaria(self)
        foto = self.tmp / 'foto.jpg'
        Image.new('RGB', (60, 80), 'white').save(foto)
        self.pasta = self.tmp / 'musicas' / 'hino' / 'revisao' / '20261107-120000'
        self.tarefa = {'pasta': str(self.pasta), 'raiz': str(self.tmp), 'clave': 'fa', 'motor': 'homr', 'versao_dir': None,
                       'paginas': [{'caminho': str(foto), 'giro': 0}],
                       'musica': {'id': 'hino', 'titulo': 'Hino', 'instrumento': 'Tuba', 'ultimo_compasso': 12}}
        for alvo, valor in [('partituras.revisao.motores.disponibilidade', {'audiveris': True}),
                            ('partituras.revisao.imagens.preparar_audiveris', (self.tmp / 'p.pdf', [], []))]:
            m = mock.patch(alvo, return_value=valor)
            m.start()
            self.addCleanup(m.stop)

    def _audiveris(self, erro):
        def rodar(pdf, pasta, progresso):
            (Path(pasta) / 'audiveris.log').write_text('WARN Too large image', encoding='utf-8')
            raise erro
        return mock.patch('partituras.revisao.motores.rodar_audiveris', side_effect=rodar)

    def test_audiveris_falha_e_o_pacote_sai_sem_guias(self):
        with self._audiveris(ErroConversao('O Audiveris não gerou partitura. Detalhes em audiveris.log.')):
            r = revisao.montar(self.tarefa, lambda *a: None)
        self.assertTrue(r['ok'])
        self.assertIn('sem guias', r['aviso'])
        pedido = (self.pasta / 'PEDIDO.md').read_text(encoding='utf-8')
        self.assertIn('não tem guias de altura', pedido)
        self.assertIn('audiveris.log', pedido)
        self.assertTrue((self.pasta / 'audiveris.log').exists())
        self.assertTrue((self.pasta / 'pagina-01.jpg').exists())
        self.assertFalse((self.pasta / '.trabalho').exists())
        self.assertFalse((self.pasta / 'guias').exists())

    def test_com_guias_sem_aviso(self):
        with mock.patch('partituras.revisao.motores.rodar_audiveris', return_value=([], self.tmp / 'a.omr')), \
                mock.patch('partituras.revisao.guias.gerar', return_value=['pagina1-sistema1-a.jpg']):
            r = revisao.montar(self.tarefa, lambda *a: None)
        self.assertNotIn('aviso', r)
        self.assertIn('use as imagens de `guias/`', (self.pasta / 'PEDIDO.md').read_text(encoding='utf-8'))
        self.assertFalse((self.pasta / '.trabalho').exists())

    def test_cancelar_nao_vira_pacote_sem_guias(self):
        with self._audiveris(Cancelado('cancelado')), self.assertRaises(Cancelado):
            revisao.montar(self.tarefa, lambda *a: None)
        self.assertFalse((self.pasta / '.trabalho').exists())


if __name__ == '__main__':
    unittest.main()

import unittest

from partituras import musicxml as mx
from testes.util import DADOS, assinatura, homr_unido, partitura


class TestPaginasEPausas(unittest.TestCase):
    def test_homr_vira_93_compassos_reais(self):
        t = homr_unido()
        mx.normalizar_multirests(t)
        self.assertEqual(len(mx.partes(t)[0].findall('measure')), 93)

    def test_audiveris_mantem_76(self):
        t = mx.ler(DADOS / 'audiveris.mxl')
        mx.normalizar_multirests(t)
        self.assertEqual(len(mx.partes(t)[0].findall('measure')), 76)

    def test_segunda_pagina_tem_quebra_e_nao_repete_armadura(self):
        t = homr_unido()
        medidas = mx.partes(t)[0].findall('measure')
        inicio_p2 = next(m for m in medidas if m.find("print[@new-page='yes']") is not None)
        self.assertIsNone(inicio_p2.find('attributes/clef'))

    def test_pausa_longa_do_homr_vira_n_compassos(self):
        t = partitura([('C3', 8)], {'notas': [], 'extra': '<attributes><measure-style><multiple-rest>5</multiple-rest></measure-style></attributes>'}, [('E3', 8)])
        mx.normalizar_multirests(t)
        self.assertEqual(len(mx.partes(t)[0].findall('measure')), 7)


class TestLigaduras(unittest.TestCase):
    def setUp(self):
        self.t = homr_unido()
        mx.normalizar_multirests(self.t)
        self.mudancas = mx.ligaduras_de_valor(self.t)

    def test_nove_ligaduras_de_valor(self):
        self.assertEqual(len(self.mudancas), 9)
        self.assertEqual(len(self.t.getroot().findall('.//slur')), 0)

    def test_acidente_passa_pela_ligadura(self):
        """O homr escreveu Dó♯ no c.19 do original (16 no rascunho); ligado a um Dó♮, tem de ser Dó♮."""
        self.assertTrue(any('acidente mantido' in m for m in self.mudancas))
        for nota in self.t.getroot().iter('note'):
            if nota.find("tie[@type='stop']") is not None and nota.findtext('pitch/step') == 'C' and nota.findtext('pitch/octave') == '3':
                if nota.findtext('pitch/alter') in (None, '0'):
                    continue
                # Dó♯3 ligado só é aceitável na ligadura do c.14–15 do original (que é Dó♯ de verdade)
                self.assertEqual(nota.findtext('pitch/alter'), '1')

    def test_curva_entre_notas_diferentes_continua_curva(self):
        t = partitura([('C3', 8)], [('D3', 8)])
        notas = list(t.getroot().iter('note'))
        for nota, tipo in zip(notas, ('start', 'stop')):
            import xml.etree.ElementTree as ET
            n = ET.SubElement(nota, 'notations')
            ET.SubElement(n, 'slur', {'type': tipo, 'number': '1'})
        self.assertEqual(mx.ligaduras_de_valor(t), [])
        self.assertEqual(len(t.getroot().findall('.//slur')), 2)


class TestTrechosDePausa(unittest.TestCase):
    def test_correcao_completa_bate_com_a_revisada(self):
        """Com os números de pausa lidos na partitura, as notas do homr batem 100% com a transcrição revisada."""
        t = homr_unido()
        mx.normalizar_multirests(t)
        mx.ligaduras_de_valor(t)
        trechos = mx.trechos_de_pausa(t)
        revisada = mx.ler(DADOS / 'revisada.musicxml')
        certos = mx.trechos_de_pausa(revisada)
        self.assertEqual(len(trechos), len(certos))
        mx.corrigir_trechos(t, {a['indice']: b['lidos'] for a, b in zip(trechos, certos)})
        mh = mx.partes(t)[0].findall('measure')
        mv = mx.partes(revisada)[0].findall('measure')
        self.assertEqual(len(mh), 165)
        comparados = [(assinatura(a), assinatura(b)) for a, b in zip(mh, mv) if assinatura(b)]
        self.assertEqual(len(comparados), 33)
        for a, b in comparados:
            self.assertEqual(a, b)

    def test_correcao_nao_deixa_numero_antigo_nem_alarme_falso(self):
        from partituras import conferencia
        t = homr_unido()
        mx.normalizar_multirests(t)
        mx.ligaduras_de_valor(t)
        mx.corrigir_trechos(t, dict(enumerate([11, 19, 37, 6, 45, 2, 2, 2, 2, 6], 1)))
        rel = conferencia.analisar(t, 'homr', 165)
        self.assertEqual(rel['suspeitos'], [])
        self.assertEqual(rel['diferenca'], 0)
        self.assertEqual([p['lido'] for p in rel['pausas_longas']][:4], [11, 19, 37, 6])

    def test_trecho_de_um_compasso_vira_varios_e_mantem_barra(self):
        t = partitura([('C3', 8)], {'notas': [('R', 8)], 'extra': '<barline location="right"><bar-style>light-light</bar-style></barline>'}, [('E3', 8)])
        self.assertEqual([x['lidos'] for x in mx.trechos_de_pausa(t)], [1])
        mx.corrigir_trechos(t, {1: 4})
        medidas = mx.partes(t)[0].findall('measure')
        self.assertEqual(len(medidas), 6)
        self.assertIsNotNone(medidas[4].find('barline'))  # barra dupla foi para o último compasso do trecho
        self.assertIsNone(medidas[1].find('barline'))
        self.assertEqual(medidas[1].findtext('attributes/measure-style/multiple-rest'), '4')

    def test_trecho_reduzido(self):
        t = partitura([('C3', 8)], [('R', 8)], [('R', 8)], [('R', 8)], [('R', 8)], [('E3', 8)])
        mx.corrigir_trechos(t, {1: 2})
        self.assertEqual(len(mx.partes(t)[0].findall('measure')), 4)

    def test_armadura_separa_trechos(self):
        t = partitura([('C3', 8)], [('R', 8)], {'notas': [('R', 8)], 'extra': '<attributes><key><fifths>-5</fifths></key></attributes>'}, [('E3', 8)])
        self.assertEqual([(x['inicio'], x['lidos']) for x in mx.trechos_de_pausa(t)], [(2, 1), (3, 1)])


class TestCabecalho(unittest.TestCase):
    def test_remove_ocr_e_define_textos(self):
        t = mx.ler(DADOS / 'audiveris.mxl')
        textos = mx.ajustar(t, 'Título', 'Trombone', 'Fulano')
        raiz = t.getroot()
        self.assertTrue(textos)
        self.assertIsNone(raiz.find('credit'))
        self.assertIsNone(raiz.find('movement-title'))
        self.assertEqual(raiz.findtext('work/work-title'), 'Título')
        self.assertEqual(raiz.findtext('identification/creator'), 'Fulano')
        self.assertEqual({e.text for e in raiz.iter('part-name')}, {'Trombone'})


if __name__ == '__main__':
    unittest.main()

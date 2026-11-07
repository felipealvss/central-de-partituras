import unittest

from partituras import conferencia
from partituras import musicxml as mx
from testes.util import assinatura, dado, homr_unido, partitura


class TestPaginasEPausas(unittest.TestCase):
    def test_homr_vira_93_compassos_reais(self):
        t = homr_unido()
        mx.normalizar_multirests(t)
        self.assertEqual(len(mx.partes(t)[0].findall('measure')), 93)

    def test_audiveris_mantem_76(self):
        t = mx.ler(dado('audiveris.mxl'))
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
        revisada = mx.ler(dado('revisada.musicxml'))
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
        t = mx.ler(dado('audiveris.mxl'))
        textos = mx.ajustar(t, 'Título', 'Trombone', 'Fulano')
        raiz = t.getroot()
        self.assertTrue(textos)
        self.assertIsNone(raiz.find('credit'))
        self.assertIsNone(raiz.find('movement-title'))
        self.assertEqual(raiz.findtext('work/work-title'), 'Título')
        self.assertEqual(raiz.findtext('identification/creator'), 'Fulano')
        self.assertEqual({e.text for e in raiz.iter('part-name')}, {'Trombone'})


def _pausa_longa(n, atributos=''):
    return {'notas': [], 'extra': f'<attributes>{atributos}<measure-style><multiple-rest>{n}</multiple-rest></measure-style></attributes>'}


QUATRO_POR_QUATRO = '<time><beats>4</beats><beat-type>4</beat-type></time>'


class TestTrechosComFormula(unittest.TestCase):
    """Fim de uma música real: impresso 2 (4/4) | nova armadura, 5 em 3/4 | 3 em 4/4 | 1 com fermata. O homr leu
    2 | [4/4] 4 | 2 | 1: errou os números e a fórmula, e o trecho 2 junta três pausas de fórmulas diferentes."""

    def _como_o_homr_leu(self):
        t = partitura([('C3', 8)], _pausa_longa(2),
                      _pausa_longa(4, '<key><fifths>-2</fifths></key>' + QUATRO_POR_QUATRO), _pausa_longa(2),
                      {'notas': [('r', 8)], 'extra': '<barline location="right"><bar-style>light-heavy</bar-style></barline>'})
        mx.normalizar_multirests(t)
        return t

    def test_trechos_trazem_a_formula_e_as_pausas_lidas(self):
        trechos = mx.trechos_de_pausa(self._como_o_homr_leu())
        self.assertEqual([(x['inicio'], x['fim'], x['lidos'], x['compasso']) for x in trechos], [(2, 3, 2, '4/4'), (4, 10, 7, '4/4')])
        self.assertEqual([g['n'] for g in trechos[1]['grupos']], [4, 2, 1])

    def test_grupos_com_formula_de_compasso(self):
        t = self._como_o_homr_leu()
        base = mx.trechos_de_pausa(t, com_elementos=True)
        correcao = {2: [(5, '3/4'), (3, '4/4'), (1, '')]}
        feitas = mx.corrigir_trechos(t, correcao)
        ms = mx.partes(t)[0].findall('measure')
        self.assertEqual(len(ms), 12)
        self.assertEqual((mx._formula(ms[3]), mx._pausa_longa(ms[3]), ms[3].findtext('attributes/key/fifths')), ((3, 4), 5, '-2'))
        self.assertEqual((mx._formula(ms[8]), mx._pausa_longa(ms[8])), ((4, 4), 3))
        self.assertEqual([mx._formula(m) for m in ms[4:8] + ms[9:]], [None] * 7)
        final = ms[11]
        self.assertEqual((final.find('note/rest').get('measure'), final.findtext('note/duration')), ('yes', '8'))
        self.assertIsNotNone(final.find('barline'))
        self.assertEqual(feitas, [{'indice': 2, 'lidos': 7, 'corrigido': 9, 'grupos': [[5, '3/4'], [3, '4/4'], [1, '']]}])
        rel = conferencia.analisar(t, 'homr', 12, trechos=mx.situar_trechos(base, correcao))
        self.assertEqual((rel['total'], rel['diferenca'], rel['duracao_errada'], rel['suspeitos']), (12, 0, [], []))
        self.assertEqual([(x['indice'], x['inicio'], x['fim'], x['lidos'], x['motor']) for x in rel['trechos']],
                         [(1, 2, 3, 2, 2), (2, 4, 12, 9, 7)])
        # Na partitura corrigida a fórmula nova divide o trecho 2 em dois; o relatório segue com os índices do motor.
        self.assertEqual(len(mx.trechos_de_pausa(t)), 3)

    def test_compasso_seguinte_continua_na_formula_que_tinha(self):
        t = partitura([('C3', 8)], _pausa_longa(3), [('E3', 8)])
        mx.normalizar_multirests(t)
        mx.corrigir_trechos(t, {1: [(3, '3/4')]})
        ms = mx.partes(t)[0].findall('measure')
        self.assertEqual((mx._formula(ms[1]), mx._formula(ms[4])), ((3, 4), (4, 4)))
        self.assertEqual(conferencia.analisar(t)['duracao_errada'], [])

    def test_formula_lida_a_mais_e_retirada(self):
        tres = '<attributes><time><beats>3</beats><beat-type>4</beat-type></time></attributes>'
        t = partitura({'notas': [('C3', 6)], 'extra': tres}, _pausa_longa(2, QUATRO_POR_QUATRO))
        mx.normalizar_multirests(t)
        mx.corrigir_trechos(t, {1: [(2, '3/4')]})  # a música continua em 3/4: o 4/4 lido sai
        ms = mx.partes(t)[0].findall('measure')
        self.assertEqual((mx._formula(ms[1]), mx._pausa_longa(ms[1])), (None, 2))

    def test_correcoes_invalidas(self):
        for ruim in [{1: [(0, '3/4')]}, {1: [(2, '3-4')]}, {1: [(2, '0/4')]}, {1: 'x'}, {1: 1000}, {'a': 2}, {1: [[]]}]:
            with self.assertRaises(ValueError, msg=ruim):
                mx.validar_correcoes(ruim)
        self.assertEqual(mx.validar_correcoes({'7': [[5, '3/4'], [3, '4/4'], [1, None]], '2': '8', '3': ''}),
                         {7: [(5, '3/4'), (3, '4/4'), (1, '')], 2: 8})


if __name__ == '__main__':
    unittest.main()

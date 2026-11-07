import io
import json
import tempfile
import threading
import unittest
from pathlib import Path

from PIL import Image

from partituras import fotos
from partituras.biblioteca import Biblioteca, Conflito, Invalido
from testes.util import RAIZ_PROJETO


def jpeg(hora=None, cor='white'):
    im = Image.new('RGB', (300, 420), cor)
    exif = im.getexif()
    if hora:
        exif.get_ifd(0x8769)[36867] = hora
    buf = io.BytesIO()
    im.save(buf, 'JPEG', exif=exif)
    buf.seek(0)
    return buf


class TestFotos(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def test_hora_pelo_exif(self):
        p = self.tmp / 'a.jpg'
        p.write_bytes(jpeg('2026:11:07 09:46:52').read())
        hora, origem = fotos.hora_da_foto(p)
        self.assertEqual((hora.hour, hora.minute, hora.second, origem), (9, 46, 52, 'exif'))

    def test_hora_pelo_nome_do_arquivo(self):
        p = self.tmp / '20261107_094659.png'
        Image.new('RGB', (10, 10)).save(p)
        hora, origem = fotos.hora_da_foto(p)
        self.assertEqual((hora.second, origem), (59, 'nome'))

    def test_heic_real_do_celular(self):
        p = RAIZ_PROJETO / 'musicas' / 'my-savior-and-my-son' / 'paginas' / '20261107_094652.heic'
        if not p.exists():
            self.skipTest('foto real não disponível')
        hora, origem = fotos.hora_da_foto(p)
        self.assertEqual((hora.hour, hora.minute, hora.second, origem), (9, 46, 52, 'exif'))

    def test_grupos_por_intervalo(self):
        itens = [{'hora': f'2026-11-07T10:00:{s:02d}'} for s in (0, 7, 20)] + [{'hora': '2026-11-07T10:05:00'}]
        grupos = fotos.sugerir_grupos(itens, limiar=90)
        self.assertEqual([len(g) for g in grupos], [3, 1])
        self.assertEqual([len(g) for g in fotos.sugerir_grupos(itens, limiar=10)], [2, 1, 1])

    def test_miniatura_em_cache(self):
        p = self.tmp / 'a.jpg'
        p.write_bytes(jpeg().read())
        m1 = fotos.miniatura(p, 90, 200, self.tmp / 'cache')
        with Image.open(m1) as im:
            self.assertEqual(im.size, (200, 143))  # girada 90°: fica deitada
        self.assertEqual(fotos.miniatura(p, 90, 200, self.tmp / 'cache'), m1)


class TestBiblioteca(unittest.TestCase):
    def setUp(self):
        self.b = Biblioteca(Path(tempfile.mkdtemp()))
        self.nomes = []
        for i, (hora, cor) in enumerate([('2026:11:07 10:00:07', 'white'), ('2026:11:07 10:00:00', 'gray'),
                                         ('2026:11:07 10:30:00', 'black')]):
            r = self.b.importar(f'foto{i}.jpg', jpeg(hora, cor))
            self.assertFalse(r['duplicada'])
            self.nomes.append(r['arquivo'])

    def test_entrada_ordenada_e_grupos(self):
        entrada = self.b.fotos_entrada()
        self.assertEqual([f['arquivo'] for f in entrada], ['foto1.jpg', 'foto0.jpg', 'foto2.jpg'])
        self.assertEqual([len(g) for g in self.b.grupos_sugeridos(90)], [2, 1])

    def test_duplicada_e_detectada(self):
        r = self.b.importar('outra.jpg', jpeg('2026:11:07 10:00:07', 'white'))
        self.assertTrue(r['duplicada'])
        self.assertEqual(len(self.b.fotos_entrada()), 3)

    def test_criar_musica_ordena_pela_hora(self):
        m = self.b.criar('Grandioso És Tu', ['foto0.jpg', 'foto1.jpg'], instrumento='Tuba')
        self.assertEqual(m['id'], 'grandioso-es-tu')
        self.assertEqual([p['arquivo'] for p in m['paginas']], ['foto1.jpg', 'foto0.jpg'])
        self.assertEqual([f['arquivo'] for f in self.b.fotos_entrada()], ['foto2.jpg'])
        self.assertEqual(self.b.saida(m)[1], 'Grandioso És Tu - Tuba')
        self.assertEqual(self.b.criar('Grandioso És Tu')['id'], 'grandioso-es-tu-2')

    def test_conflito_de_edicao(self):
        m = self.b.criar('Hino', ['foto2.jpg'])
        self.b.atualizar(m['id'], m['revisao'], {'titulo': 'Hino 15'})
        with self.assertRaises(Conflito):
            self.b.atualizar(m['id'], m['revisao'], {'titulo': 'Outro'})

    def test_ordem_e_giro_das_paginas(self):
        m = self.b.criar('Hino', ['foto0.jpg', 'foto1.jpg'])
        m = self.b.atualizar(m['id'], m['revisao'], {'paginas': [{'arquivo': 'foto0.jpg', 'giro': 90}, {'arquivo': 'foto1.jpg'}]})
        self.assertEqual([(p['arquivo'], p['giro']) for p in m['paginas']], [('foto0.jpg', 90), ('foto1.jpg', 0)])
        with self.assertRaises(Invalido):
            self.b.atualizar(m['id'], m['revisao'], {'paginas': [{'arquivo': 'foto0.jpg'}]})

    def test_devolver_pagina_mantem_giro(self):
        m = self.b.criar('Hino', ['foto0.jpg', 'foto1.jpg'])
        m = self.b.atualizar(m['id'], m['revisao'], {'paginas': [{'arquivo': 'foto1.jpg'}, {'arquivo': 'foto0.jpg', 'giro': 180}]})
        m = self.b.devolver_pagina(m['id'], 'foto0.jpg')
        self.assertEqual([p['arquivo'] for p in m['paginas']], ['foto1.jpg'])
        volta = next(f for f in self.b.fotos_entrada() if f['arquivo'] == 'foto0.jpg')
        self.assertEqual(volta['giro'], 180)

    def test_gravacao_concorrente_sem_perda(self):
        m = self.b.criar('Hino', ['foto2.jpg'])
        erros = []

        def editar(campo, valor):
            for _ in range(50):
                atual = self.b.ler(m['id'])
                try:
                    self.b.atualizar(m['id'], atual['revisao'], {campo: valor})
                    return
                except Conflito:
                    continue
            erros.append(campo)

        ts = [threading.Thread(target=editar, args=a) for a in (('titulo', 'T'), ('instrumento', 'Tuba'), ('compositor', 'C'))]
        [t.start() for t in ts]
        [t.join() for t in ts]
        final = self.b.ler(m['id'])
        self.assertEqual(erros, [])
        self.assertEqual((final['titulo'], final['instrumento'], final['compositor']), ('T', 'Tuba', 'C'))
        json.loads((self.b.musicas / m['id'] / 'musica.json').read_text())

    def test_conversao_e_estado(self):
        m = self.b.criar('Hino', ['foto2.jpg'])
        cid, pasta = self.b.nova_conversao(m['id'], 'homr')
        self.assertTrue(pasta.is_dir())
        self.assertEqual(self.b.ler(m['id'])['estado'], 'nova')  # na fila só quando a fila assumir
        self.b.definir_estado(m['id'], 'convertendo', cid)
        self.assertEqual(self.b.ler(m['id'])['estado'], 'convertendo')
        self.b.registrar_versao(m['id'], cid, {'ok': True, 'versao': 1, 'publicados': {}, 'resumo': {'alertas': True}})
        self.assertEqual(self.b.ler(m['id'])['estado'], 'rascunho_alertas')
        m = self.b.ler(m['id'])
        self.b.atualizar(m['id'], m['revisao'], {'revisada': True})
        self.assertEqual(self.b.ler(m['id'])['estado'], 'revisada')


class TestEstadoDeMusicaRevisada(unittest.TestCase):
    def test_revisada_reconvertida_volta_a_revisada(self):
        b = Biblioteca(Path(tempfile.mkdtemp()))
        b.importar('a.jpg', jpeg('2026:11:07 10:00:00'))
        m = b.criar('Hino', ['a.jpg'])
        m = b.atualizar(m['id'], m['revisao'], {'revisada': True})
        cid, _ = b.nova_conversao(m['id'], 'homr')
        b.definir_estado(m['id'], 'convertendo', cid)
        self.assertEqual(b.ler(m['id'])['estado'], 'convertendo')
        b.registrar_versao(m['id'], cid, {'ok': True, 'versao': 1, 'resumo': {'alertas': True}})
        self.assertEqual(b.ler(m['id'])['estado'], 'revisada')

    def test_conversao_legada_nao_vira_erro(self):
        b = Biblioteca(Path(tempfile.mkdtemp()))
        m = b.criar('Hino')
        m['conversoes'].append({'id': 'antiga', 'estado': 'legado', 'versoes': []})
        m['revisada'] = True
        b._salvar(m)
        m = b.atualizar(m['id'], m['revisao'], {'revisada': False})
        self.assertEqual(m['estado'], 'nova')


if __name__ == '__main__':
    unittest.main()

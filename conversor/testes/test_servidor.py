import json
import os
import sys
import tempfile
import time
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from partituras.biblioteca import Biblioteca
from partituras.fila import Fila
from partituras.servidor import criar_app
from testes.test_biblioteca import jpeg

TOKEN = 'ficha-de-teste'
H = {'X-Central': '1'}

FALSO = r'''
import json, os, subprocess, sys
from pathlib import Path
t = json.loads(Path(sys.argv[1]).read_text())
print(json.dumps({'etapa': 'reconhecendo', 'msg': 'página 1 de 1', 'i': 1, 'n': 1}), flush=True)
if os.environ.get('FALSO_MODO') == 'demorado':
    p = subprocess.Popen(['sleep', '60'])
    Path(t['conv'], 'neto.pid').write_text(str(p.pid))
    p.wait()
v = Path(t['conv']) / 'versoes' / '01'
v.mkdir(parents=True, exist_ok=True)
print(json.dumps({'fim': True, 'ok': True, 'versao': 1, 'publicados': {}, 'resumo': {'alertas': True, 'total': 10}}), flush=True)
'''


def falso(tarefa):
    return [sys.executable, '-c', FALSO, str(tarefa)]


def esperar(cond, segundos=15):
    limite = time.monotonic() + segundos
    while time.monotonic() < limite:
        if cond():
            return True
        time.sleep(0.1)
    return False


class Base(unittest.TestCase):
    def setUp(self):
        self.b = Biblioteca(Path(tempfile.mkdtemp()))
        self.fila = Fila(self.b, comando=falso, verificar_motores=False)
        self.app = criar_app(self.b, self.fila, TOKEN)
        self.c = self.app.test_client()
        self.c.set_cookie('central', TOKEN, domain='127.0.0.1')
        self.base = {'base_url': 'http://127.0.0.1:8765'}

    def get(self, url, **kw):
        return self.c.get(url, **self.base, **kw)

    def envia(self, metodo, url, **kw):
        return getattr(self.c, metodo)(url, headers=H, **self.base, **kw)

    def musica_com_foto(self):
        self.envia('put', '/api/entrada/pagina1.jpg', data=jpeg('2026:11:07 10:00:00').read())
        r = self.envia('post', '/api/entrada/criar', json={'grupos': [{'titulo': 'Hino 15', 'fotos': ['pagina1.jpg']}]})
        return r.get_json()['musicas'][0]


class TestSeguranca(Base):
    def test_sem_cookie_e_negado(self):
        c = self.app.test_client()
        self.assertEqual(c.get('/api/musicas', **self.base).status_code, 403)
        r = c.get(f'/?t={TOKEN}', **self.base)
        self.assertEqual(r.status_code, 302)
        self.assertIn('SameSite=Strict', r.headers['Set-Cookie'])
        self.assertEqual(c.get('/api/musicas', **self.base).status_code, 200)

    def test_host_estranho_e_negado(self):
        self.assertEqual(self.c.get('/api/musicas', base_url='http://evil.example:8765').status_code, 403)

    def test_alterar_sem_cabecalho_e_negado(self):
        self.assertEqual(self.c.post('/api/musicas', json={'titulo': 'X'}, **self.base).status_code, 403)

    def test_caminho_com_ponto_ponto(self):
        self.assertEqual(self.get('/api/imagem/entrada/..%2F..%2F..%2Fetc%2Fpasswd').status_code, 404)
        self.assertEqual(self.get('/api/musicas/..%2F..%2F.estado').status_code, 404)

    def test_abrir_so_arquivos_da_musica(self):
        m = self.musica_com_foto()
        with mock.patch('partituras.sistema.abrir') as abrir:
            r = self.envia('post', '/api/sistema/abrir', json={'musica': m['id'], 'arquivo': '/etc/passwd'})
            self.assertEqual(r.status_code, 404)
            abrir.assert_not_called()


class TestFluxo(Base):
    def test_enviar_agrupar_e_miniatura(self):
        m = self.musica_com_foto()
        self.assertEqual(m['id'], 'hino-15')
        self.assertEqual(self.get('/api/entrada').get_json()['fotos'], [])
        r = self.get(f"/api/imagem/musica/{m['id']}/pagina1.jpg?lado=200")
        self.assertEqual((r.status_code, r.mimetype), (200, 'image/jpeg'))

    def test_conflito_retorna_409(self):
        m = self.musica_com_foto()
        self.envia('patch', f"/api/musicas/{m['id']}", json={'revisao': m['revisao'], 'mudancas': {'titulo': 'A'}})
        r = self.envia('patch', f"/api/musicas/{m['id']}", json={'revisao': m['revisao'], 'mudancas': {'titulo': 'B'}})
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.get_json()['musica']['titulo'], 'A')

    def test_fila_converte(self):
        m = self.musica_com_foto()
        r = self.envia('post', f"/api/musicas/{m['id']}/converter")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(esperar(lambda: self.b.ler(m['id'])['estado'] == 'rascunho_alertas'))
        conv = self.b.ler(m['id'])['conversoes'][-1]
        self.assertEqual((conv['estado'], len(conv['versoes'])), ('ok', 1))

    def test_cancelar_encerra_o_processo_neto(self):
        m = self.musica_com_foto()
        with mock.patch.dict(os.environ, {'FALSO_MODO': 'demorado'}):
            job = self.envia('post', f"/api/musicas/{m['id']}/converter").get_json()['trabalhos'][0]
            cid = self.b.ler(m['id'])['conversoes'][-1]['id']
            pidfile = self.b.pasta_conversao(m['id'], cid) / 'neto.pid'
            self.assertTrue(esperar(pidfile.exists))
            neto = int(pidfile.read_text())
            self.assertTrue(self.envia('delete', f'/api/fila/{job}').get_json()['ok'])
            self.assertTrue(esperar(lambda: self.b.ler(m['id'])['estado'] == 'cancelada'))
            time.sleep(0.3)
            with self.assertRaises(ProcessLookupError):
                os.kill(neto, 0)

    def test_retomada_depois_de_reiniciar(self):
        m = self.musica_com_foto()
        cid, _ = self.b.nova_conversao(m['id'], 'homr')
        self.b.definir_estado(m['id'], 'convertendo', cid)
        Fila(self.b, comando=falso, verificar_motores=False).recuperar()
        self.assertEqual(self.b.ler(m['id'])['estado'], 'interrompida')

    def test_exportar_zip(self):
        m = self.musica_com_foto()
        r = self.envia('post', '/api/exportar', json={'musicas': [m['id']], 'mostrar': False})
        self.assertEqual(r.status_code, 200)
        with zipfile.ZipFile(r.get_json()['arquivo']) as z:
            nomes = set(z.namelist())
        self.assertTrue({'fotos/pagina-01.jpg', 'musica.json', 'LEIA-ME.txt'} <= nomes)
        json.loads(zipfile.ZipFile(r.get_json()['arquivo']).read('musica.json'))


if __name__ == '__main__':
    unittest.main()

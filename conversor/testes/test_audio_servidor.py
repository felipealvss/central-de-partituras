"""Modo de áudio na biblioteca, na fila e no servidor, com um trabalhador de áudio falso (roda no Python do
servidor: nenhuma dependência de áudio). O trabalhador real é testado em test_audio_trabalho.py."""
import json
import os
import sys
import time
import unittest
import wave
from pathlib import Path
from unittest import mock

from partituras.biblioteca import Biblioteca
from partituras.fila import Fila
from partituras.servidor import criar_app
from testes.test_servidor import H, TOKEN, esperar, falso
from testes.util import temporaria

FALSO_AUDIO = r'''
import json, os, subprocess, sys, wave
from pathlib import Path
t = json.loads(Path(sys.argv[1]).read_text())
print('ruído de biblioteca que não é JSON', flush=True)
if t['tipo'] == 'baixar':
    print(json.dumps({'etapa': 'baixando', 'msg': '50%', 'i': 1, 'n': 2}), flush=True)
    if os.environ.get('FALSO_MODO') == 'demorado':
        subprocess.Popen(['sleep', '60']).wait()
    arq = Path(t['pasta_audio']) / 'original.wav'
    with wave.open(str(arq), 'wb') as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(8000); w.writeframes(b'\x00\x01' * 8000)
    print(json.dumps({'fim': True, 'ok': True, 'audio': {'arquivo': 'original.wav', 'codec': 'pcm_s16le',
          'duracao': 1.0, 'hash': 'f' * 16, 'titulo_original': 'Vídeo de teste'}}), flush=True)
    sys.exit(0)
print(json.dumps({'etapa': 'separando', 'msg': 'trecho 1 de 3', 'i': 1, 'n': 3}), flush=True)
if os.environ.get('FALSO_MODO') == 'demorado':
    p = subprocess.Popen(['sleep', '60'])
    Path(t['conv'], 'neto.pid').write_text(str(p.pid))
    p.wait()
v = Path(t['conv']) / 'versoes'
n = 1 + len(list(v.glob('*'))) if v.exists() else 1
pasta = v / f'{n:02d}'
pasta.mkdir(parents=True)
(pasta / 'trecho-01.png').write_bytes(b'\x89PNG\r\n\x1a\n')
(pasta / 'conferencia.json').write_text(json.dumps({'tipo': 'audio', 'ajustes': t['ajustes'], 'instrumento': t['instrumento']}))
print(json.dumps({'fim': True, 'ok': True, 'versao': n, 'publicados': {}, 'resumo': {'alertas': False, 'notas': 10},
      'conversao': {'separacao': {'modelo': 'mega53-v1', 'segundos': 1.0}}, 'audio': {'presenca': {'saxophone': 0.15}}}),
      flush=True)
'''


def falso_audio(tarefa):
    return [sys.executable, '-c', FALSO_AUDIO, str(tarefa)]


def wav(caminho, segundos=1.0, taxa=8000, valor=b'\x00\x01'):
    with wave.open(str(caminho), 'wb') as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(taxa)
        w.writeframes(valor * int(segundos * taxa))
    return caminho


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = temporaria(self)
        self.b = Biblioteca(self.tmp / 'raiz')
        self.fila = Fila(self.b, comando=falso, comando_audio=falso_audio, verificar_motores=False)
        self.app = criar_app(self.b, self.fila, TOKEN)
        self.c = self.app.test_client()
        self.c.set_cookie('central', TOKEN, domain='127.0.0.1')
        self.base = {'base_url': 'http://127.0.0.1:8765'}
        p = mock.patch('partituras.servidor.caminhos.TEMPORARIOS', self.tmp / 'tmp')
        p.start()
        self.addCleanup(p.stop)

    def get(self, url, **kw):
        return self.c.get(url, **self.base, **kw)

    def envia(self, metodo, url, **kw):
        return getattr(self.c, metodo)(url, headers={**H, **kw.pop('headers', {})}, **self.base, **kw)

    def enviar_audio(self, nome='gravacao.wav', converter=False, valor=b'\x00\x01', **params):
        dados = wav(self.tmp / f'x-{len(os.listdir(self.tmp))}.wav', valor=valor).read_bytes()
        query = '&'.join(f'{k}={v}' for k, v in {'titulo': 'Hino 15', **params}.items())
        return self.envia('put', f"/api/audio/arquivo/{nome}?{query}{'&converter=1' if converter else ''}", data=dados)


class TestImportarAudio(Base):
    def test_cria_musica_de_audio(self):
        r = self.enviar_audio(instrumento='sax-alto')
        self.assertEqual(r.status_code, 201, r.get_json())
        m = r.get_json()['musica']
        self.assertEqual((m['fonte'], m['instrumento_alvo'], m['instrumento'], m['estado']),
                         ('audio', 'sax-alto', 'Sax alto', 'nova'))
        self.assertEqual((m['audio']['codec'], m['audio']['com_perdas'], m['audio']['arquivo']),
                         ('pcm_s16le', False, 'original.wav'))
        self.assertTrue((self.b.musicas / m['id'] / 'audio' / 'original.wav').is_file())
        self.assertEqual(list((self.tmp / 'tmp').iterdir()), [])  # temporário apagado

    def test_duplicado_extensao_e_conteudo(self):
        self.assertEqual(self.enviar_audio().status_code, 201)
        r = self.enviar_audio()
        self.assertEqual((r.status_code, r.get_json()['onde']), (409, 'hino-15'))
        self.assertEqual(self.enviar_audio(nome='foto.heic', valor=b'\x00\x02').status_code, 400)
        r = self.envia('put', '/api/audio/arquivo/falso.mp3?titulo=X', data=b'isto nao e audio')
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.enviar_audio(instrumento='kazoo', valor=b'\x00\x03').status_code, 400)

    def test_lista_instrumentos_e_estado_do_audio(self):
        d = self.get('/api/musicas').get_json()
        self.assertEqual(d['instrumento_padrao'], 'sax-tenor')
        self.assertIn('trombone', [i['id'] for i in d['instrumentos_audio']])
        self.assertIn('pronto', self.get('/api/estado').get_json()['audio'])

    def test_campos_de_fotos_recusados(self):
        m = self.enviar_audio().get_json()['musica']
        url = f"/api/musicas/{m['id']}"
        r = self.envia('patch', url, json={'revisao': m['revisao'], 'mudancas': {'motor': 'homr'}})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.envia('post', f'{url}/paginas', json={'fotos': ['a.jpg']}).status_code, 400)
        self.assertEqual(self.envia('post', f'{url}/revisao').status_code, 400)
        r = self.envia('patch', url, json={'revisao': m['revisao'], 'mudancas': {'instrumento_alvo': 'trompete'}})
        self.assertEqual(r.get_json()['instrumento'], 'Trompete em Si♭')  # o nome da parte acompanha
        m = r.get_json()
        r = self.envia('patch', url, json={'revisao': m['revisao'], 'mudancas': {'instrumento': 'Trompete 2'}})
        m = r.get_json()
        r = self.envia('patch', url, json={'revisao': m['revisao'], 'mudancas': {'instrumento_alvo': 'trombone'}})
        self.assertEqual(r.get_json()['instrumento'], 'Trompete 2')  # nome escrito à mão não é trocado
        self.assertEqual(sorted(r.get_json()['checklist']), ['notas', 'ouvida', 'ritmo', 'trechos'])


class TestConverterAudio(Base):
    def _convertida(self):
        r = self.enviar_audio(converter=True)
        self.assertEqual(r.status_code, 201)
        mid = r.get_json()['musica']['id']
        self.assertEqual(len(r.get_json()['trabalhos']), 1)
        self.assertTrue(esperar(lambda: self.b.ler(mid)['estado'] == 'rascunho'))
        return mid, self.b.ler(mid)['conversoes'][-1]

    def test_converter_e_refazer_com_ajustes(self):
        mid, conv = self._convertida()
        self.assertEqual((conv['motor'], conv['instrumento'], conv['separacao']['modelo']), ('audio', 'sax-tenor', 'mega53-v1'))
        self.assertEqual(self.b.ler(mid)['audio']['presenca'], {'saxophone': 0.15})
        url = f"/api/musicas/{mid}/conversoes/{conv['id']}/acabar"
        self.assertEqual(self.envia('post', url, json={'ajustes': {'compasso': 9}}).status_code, 400)
        ajustes = {'trechos': {'1': False}, 'compasso': 3, 'andamento': 'dobro'}
        self.assertEqual(self.envia('post', url, json={'ajustes': ajustes}).status_code, 200)
        self.assertTrue(esperar(lambda: len(self.b.ler(mid)['conversoes'][-1]['versoes']) == 2))
        self.assertEqual(self.b.ler(mid)['conversoes'][-1]['versoes'][-1]['correcoes'],
                         {'trechos': {'1': False}, 'compasso': 3, 'andamento': 'dobro'})
        r = self.get(f"/api/musicas/{mid}/conversoes/{conv['id']}/versoes/1/trecho-01.png")
        self.assertEqual((r.status_code, r.mimetype), (200, 'image/png'))
        r.close()
        self.assertEqual(self.get(f"/api/musicas/{mid}/conversoes/{conv['id']}/versoes/1/notas.py").status_code, 404)

    def test_audio_com_range_para_o_player(self):
        mid = self.enviar_audio().get_json()['musica']['id']
        r = self.get(f'/api/musicas/{mid}/audio/original', headers={'Range': 'bytes=0-99'})
        self.assertEqual((r.status_code, r.headers.get('Content-Range', '')[:12], len(r.data)), (206, 'bytes 0-99/1', 100))
        r.close()
        self.assertEqual(self.get(f'/api/musicas/{mid}/audio/saxophone').status_code, 404)  # ainda não separado
        self.assertEqual(self.get(f'/api/musicas/{mid}/audio/..%2Fmusica.json').status_code, 404)
        self.assertEqual(self.get(f'/api/musicas/{mid}/audio/bateria').status_code, 404)

    def test_cancelar_e_excluir_durante_a_conversao(self):
        with mock.patch.dict(os.environ, {'FALSO_MODO': 'demorado'}):
            r = self.enviar_audio(converter=True)
            mid = r.get_json()['musica']['id']
            cid = self.b.ler(mid)['conversoes'][-1]['id']
            pidfile = self.b.pasta_conversao(mid, cid) / 'neto.pid'
            self.assertTrue(esperar(pidfile.exists))
            neto = int(pidfile.read_text())
            with mock.patch('partituras.biblioteca.para_lixeira') as lixeira:
                self.assertEqual(self.envia('delete', f'/api/musicas/{mid}').status_code, 200)
                lixeira.assert_called_once()
            time.sleep(0.5)
            with self.assertRaises(ProcessLookupError):
                os.kill(neto, 0)


class TestExportarAudio(Base):
    def test_zip_de_musica_de_audio(self):
        import zipfile
        mid = self.enviar_audio().get_json()['musica']['id']
        r = self.envia('post', '/api/exportar', json={'musicas': [mid], 'mostrar': False})
        self.assertEqual(r.status_code, 200, r.get_json())
        with zipfile.ZipFile(r.get_json()['arquivo']) as z:
            leia = z.read('LEIA-ME.txt').decode('utf-8')
            self.assertFalse(any(n.endswith('.wav') for n in z.namelist()))
        self.assertIn('Fonte: áudio (gravacao.wav)', leia)

class TestImportarPorLink(Base):
    def test_link_baixa_e_converte(self):
        r = self.envia('post', '/api/audio/link', json={'url': 'https://www.youtube.com/watch?v=abc', 'instrumento': 'trombone'})
        self.assertEqual(r.status_code, 201, r.get_json())
        mid = r.get_json()['musica']['id']
        self.assertTrue(esperar(lambda: self.b.ler(mid)['estado'] == 'rascunho'))
        m = self.b.ler(mid)
        self.assertEqual((m['titulo'], m['audio']['estado'], m['audio']['origem'], m['conversoes'][-1]['instrumento']),
                         ('Vídeo de teste', 'pronto', 'link', 'trombone'))

    def test_links_recusados(self):
        for url in ('ftp://x.com/a', 'youtube.com/watch?v=1', 'https://www.youtube.com/playlist?list=X', ''):
            with self.subTest(url):
                self.assertEqual(self.envia('post', '/api/audio/link', json={'url': url}).status_code, 400)

    def test_download_interrompido_ao_reiniciar(self):
        with mock.patch.object(self.fila, 'enfileirar_baixar', return_value=['x']):
            mid = self.envia('post', '/api/audio/link', json={'url': 'https://example.com/v'}).get_json()['musica']['id']
        self.assertEqual(self.b.ler(mid)['estado'], 'baixando')
        Fila(self.b, comando=falso, comando_audio=falso_audio, verificar_motores=False).recuperar()
        m = self.b.ler(mid)
        self.assertEqual((m['estado'], m['audio']['estado']), ('interrompida', 'interrompido'))

    def test_fila_antiga_sem_ambiente(self):
        (self.b.estado / 'fila.json').write_text(json.dumps({'itens': [
            {'id': 'a1', 'musica': 'x', 'titulo': 'X', 'motor': 'homr', 'tipo': 'converter', 'cid': 'c',
             'arquivo': '/nao/existe.json', 'correcoes': {}, 'criado': 't'}]}))
        f = Fila(self.b, comando=falso, comando_audio=falso_audio, verificar_motores=False)
        f.recuperar()
        self.assertEqual(f.estado()['fila'], [])



@unittest.skipUnless(os.environ.get('CENTRAL_PY_AUDIO') and (Path(__file__).parent / 'dados' / 'audio' / 'saxophone.flac').exists(),
                     'ponta a ponta: defina CENTRAL_PY_AUDIO (Python do ambiente de áudio) e tenha os dados do piloto')
class TestPontaAPonta(Base):
    """API → fila → trabalhador de áudio REAL → versão, com o cache de stems do piloto (sem separar de novo)."""

    def test_importar_converter_e_refazer(self):
        import shutil as sh
        from partituras import caminhos
        from partituras.audio import mega53
        dados = Path(__file__).parent / 'dados' / 'audio'
        self.fila.comando_audio = lambda t: [os.environ['CENTRAL_PY_AUDIO'], '-m', 'partituras.audio.trabalho', str(t)]
        m = self.enviar_audio(instrumento='sax-tenor').get_json()['musica']
        pasta = self.b.musicas / m['id'] / 'audio'
        sh.copyfile(dados / 'mistura.flac', pasta / 'mistura.flac')
        cache = pasta / 'separacao' / mega53.VERSAO
        cache.mkdir(parents=True)
        for stem in ('saxophone', 'trumpet', 'trombone', 'vocal'):
            sh.copyfile(dados / f'{stem}.flac', cache / f'{stem}.flac')
        (cache / 'separacao.json').write_text(json.dumps({'modelo': mega53.VERSAO, 'presenca': {'saxophone': 0.155}}))
        with mock.patch.dict(os.environ, {'CENTRAL_PARTITURAS_RAIZ': str(self.tmp / 'raiz')}):
            self.assertEqual(self.envia('post', f"/api/musicas/{m['id']}/converter").status_code, 200)
            self.assertTrue(esperar(lambda: self.b.ler(m['id'])['estado'] in ('rascunho', 'rascunho_alertas', 'erro'), 600))
        conv = self.b.ler(m['id'])['conversoes'][-1]
        self.assertEqual(conv['estado'], 'ok', conv.get('erro'))
        v = conv['versoes'][-1]
        self.assertEqual((v['resumo']['trechos'], v['resumo']['compasso']), (11, '4/4'))
        self.assertTrue(all(Path(p).exists() for p in v['publicados'].values()))
        conf = self.get(f"/api/musicas/{m['id']}/conversoes/{conv['id']}/versoes/1/conferencia").get_json()
        self.assertEqual((conf['tipo'], conf['tom_escrito']), ('audio', 'Ré♭ maior'))
        r = self.get(f"/api/musicas/{m['id']}/conversoes/{conv['id']}/versoes/1/sintese.flac", headers={'Range': 'bytes=0-9'})
        self.assertEqual(r.status_code, 206)
        r.close()

if __name__ == '__main__':
    unittest.main()

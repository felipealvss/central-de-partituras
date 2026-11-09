"""Separação com o "MVSep Mega 53 Stems" (BS-RoFormer) para o cache da música (audio/separacao/<versão>/).

- Só os stems pedidos são calculados (active_stem_ids): o piloto calculava os 53 e jogava 49 fora.
- Trechos com transição suave (soma com sobreposição); meia precisão na GPU; se faltar memória, o trecho
  diminui e, em último caso, a separação vai para o processador. O último trecho que coube fica guardado.
- O cache é gravado num diretório temporário e só então trocado no lugar: cancelar no meio não deixa stem
  pela metade com cara de pronto.

O núcleo (separar_array) é numpy puro, com o modelo injetado, para os testes não executarem a rede.
"""
import json
import os
import shutil
import time
import uuid
from pathlib import Path

import numpy as np

from . import mega53

SR = mega53.TAXA


def janela(n, borda):
    w = np.ones(n, dtype=np.float32)
    rampa = np.linspace(0, 1, borda, dtype=np.float32)
    w[:borda], w[-borda:] = rampa, rampa[::-1]
    return w


def separar_array(audio, modelo, n_stems, segundos, progresso=None, sr=SR):
    """audio: (canais, amostras). modelo(x (canais, c)) → (n_stems, canais, c). Devolve (n_stems, canais, amostras)."""
    canais, n = audio.shape
    c = max(int(segundos * sr), 8)
    passo, borda = c // 2, c // 4
    pad = np.pad(audio, ((0, 0), (borda, c + borda)))
    acum = np.zeros((n_stems, canais, pad.shape[1]), dtype=np.float32)
    peso = np.zeros(pad.shape[1], dtype=np.float32)
    w = janela(c, borda)
    inicios = list(range(0, pad.shape[1] - c + 1, passo))
    t0 = time.monotonic()
    for k, ini in enumerate(inicios):
        acum[:, :, ini:ini + c] += modelo(pad[:, ini:ini + c]) * w
        peso[ini:ini + c] += w
        if progresso and (k % 10 == 0 or k == len(inicios) - 1):
            feito = (k + 1) / len(inicios)
            resta = (time.monotonic() - t0) / feito * (1 - feito)
            progresso('separando', f'Separando: {int(feito * 100)}% (faltam ~{int(resta // 60)} min {int(resta % 60)} s)',
                      k + 1, len(inicios))
    peso[peso == 0] = 1
    return (acum / peso)[:, :, borda:borda + n]


def separar_com_reserva(audio, modelos, n_stems, segundos, erros_memoria, progresso=None, minimo=1.0):
    """Tenta cada (dispositivo, modelo) de `modelos` (ex.: GPU e depois processador); dentro de cada um, diminui o
    trecho a cada falta de memória até `minimo`. Devolve (stems, dispositivo, segundos usados)."""
    for i, (dispositivo, modelo, liberar) in enumerate(modelos):
        s = segundos if i == 0 else max(segundos, 10.0)
        while True:
            try:
                return separar_array(audio, modelo, n_stems, s, progresso), dispositivo, s
            except erros_memoria:
                liberar()
                if s <= minimo:
                    break
                s = max(minimo, s / 1.5)
                if progresso:
                    progresso('separando', f'Memória da GPU insuficiente; tentando trechos de {s:.1f} s', None, None)
    raise MemoryError('Não houve memória para separar nem com trechos mínimos.')


def presenca(stem, sr=SR):
    """Fração do tempo em que o stem soa (até 24 dB abaixo do próprio pico)."""
    mono = stem.mean(axis=0)
    n = (len(mono) // 512) * 512
    if n < 2048:
        return 0.0
    rms = np.sqrt(np.mean(mono[:n].reshape(-1, 512) ** 2, axis=1))
    db = 20 * np.log10(np.maximum(rms, 1e-9))
    return float(np.mean(db > np.percentile(db, 99.5) - 24))


def _trecho_inicial(dispositivo, arquivo_gpu):
    if dispositivo == 'cpu':
        return mega53.TRECHO_AUTOR
    try:
        return float(json.loads(Path(arquivo_gpu).read_text())['segundos'])
    except (OSError, ValueError, KeyError):
        pass
    import torch
    total = torch.cuda.get_device_properties(0).total_memory / 2 ** 30
    return 2.0 if total <= 4.5 else 6.0 if total <= 8.5 else mega53.TRECHO_AUTOR


def carregar_modelo(checkpoint, dispositivo):
    import torch
    from .bs_roformer.bs_roformer import BSRoformer
    modelo = BSRoformer(**mega53.MODELO)
    estado = torch.load(checkpoint, map_location='cpu', weights_only=True)  # só tensores: o arquivo não executa código
    for chave in ('state', 'state_dict', 'model'):
        if isinstance(estado, dict) and isinstance(estado.get(chave), dict):
            estado = estado[chave]
    modelo.load_state_dict(estado)
    return modelo.eval().to(dispositivo)


def separar(mistura, destino, checkpoint, stems, arquivo_gpu=None, progresso=None):
    """Separa `mistura` (FLAC 44,1 kHz estéreo) e grava `destino`/<stem>.flac + separacao.json, atomicamente."""
    import soundfile as sf
    import torch
    audio, sr = sf.read(str(mistura), dtype='float32', always_2d=True)
    if sr != SR:
        raise ValueError(f'A mistura precisa estar em {SR} Hz (está em {sr}).')
    audio = audio.T
    idx = [mega53.STEMS.index(s) for s in stems]
    t0 = time.monotonic()

    def preparar(dispositivo):
        if progresso:
            progresso('separando', f'Carregando o modelo de separação ({dispositivo})', None, None)
        modelo = carregar_modelo(checkpoint, dispositivo)

        def aplicar(x):
            with torch.inference_mode(), torch.autocast(device_type='cuda', dtype=torch.float16,
                                                        enabled=dispositivo == 'cuda'):
                y = modelo(torch.from_numpy(np.ascontiguousarray(x)).unsqueeze(0).to(dispositivo),
                           active_stem_ids=idx)
            return y[0].float().cpu().numpy()

        def liberar():
            if dispositivo == 'cuda':
                torch.cuda.empty_cache()
        return dispositivo, aplicar, liberar

    opcoes = [preparar('cuda')] if torch.cuda.is_available() else []
    erros = (torch.OutOfMemoryError, MemoryError)
    inicial = _trecho_inicial('cuda' if opcoes else 'cpu', arquivo_gpu)

    def modelos():
        yield from opcoes
        if opcoes:  # libera a GPU antes de ir para o processador
            opcoes.clear()
            torch.cuda.empty_cache()
            if progresso:
                progresso('separando', 'Sem memória na GPU: separando no processador (bem mais lento)', None, None)
        yield preparar('cpu')

    saida, dispositivo, segundos = separar_com_reserva(audio, modelos(), len(idx), inicial, erros, progresso)
    if dispositivo == 'cuda' and arquivo_gpu:
        Path(arquivo_gpu).parent.mkdir(parents=True, exist_ok=True)
        Path(arquivo_gpu).write_text(json.dumps({'segundos': segundos}))
    destino = Path(destino)
    tmp = destino.parent / f'.temp-{uuid.uuid4().hex[:8]}'
    tmp.mkdir(parents=True)
    try:
        for j, nome in enumerate(stems):
            sf.write(tmp / f'{nome}.flac', saida[j].T, SR, subtype='PCM_16')
        info = {'modelo': mega53.VERSAO, 'checkpoint_sha256': mega53.CHECKPOINT['sha256'], 'stems': list(stems),
                'dispositivo': dispositivo, 'trecho_s': round(segundos, 2),
                'segundos': round(time.monotonic() - t0, 1),
                'presenca': {nome: round(presenca(saida[j]), 3) for j, nome in enumerate(stems)}}
        (tmp / 'separacao.json').write_text(json.dumps(info, ensure_ascii=False, indent=1), encoding='utf-8')
        if destino.exists():
            shutil.rmtree(destino)
        os.replace(tmp, destino)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return info


def cache_valido(destino, stems):
    destino = Path(destino)
    try:
        info = json.loads((destino / 'separacao.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    if info.get('modelo') != mega53.VERSAO or not all((destino / f'{s}.flac').is_file() for s in stems):
        return None
    return info


def limpar_temporarios(pasta):
    """Restos de separações canceladas no meio (diretórios .temp-*)."""
    for p in Path(pasta).glob('.temp-*'):
        shutil.rmtree(p, ignore_errors=True)

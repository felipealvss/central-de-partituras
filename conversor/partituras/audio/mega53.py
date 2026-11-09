"""Modelo de separação "MVSep Mega 53 Stems" (BS-RoFormer; ZFTurbo/Music-Source-Separation-Training v1.0.21,
licença MIT) e o modelo de pulsação Beat This! (CPJKU, MIT): hiperparâmetros, nomes das saídas e os arquivos que o
instalador baixa, com SHA-256. Os hiperparâmetros ficam aqui como dicionário para não depender de ler o YAML
publicado (que usa tags !!python/tuple). Só biblioteca padrão."""

VERSAO = 'mega53-v1'
TAXA = 44100

MODELO = {
    'dim': 256, 'depth': 12, 'stereo': True, 'num_stems': 53, 'time_transformer_depth': 1,
    'freq_transformer_depth': 1, 'linear_transformer_depth': 0,
    'freqs_per_bands': (2,) * 24 + (4,) * 12 + (12,) * 8 + (24,) * 8 + (48,) * 8 + (128, 129),
    'dim_head': 64, 'heads': 8, 'attn_dropout': 0.0, 'ff_dropout': 0.0, 'flash_attn': True, 'dim_freqs_in': 1025,
    'stft_n_fft': 2048, 'stft_hop_length': 512, 'stft_win_length': 2048, 'stft_normalized': False,
    'mask_estimator_depth': 2, 'multi_stft_resolution_loss_weight': 1.0,
    'multi_stft_resolutions_window_sizes': (4096, 2048, 1024, 512, 256), 'multi_stft_hop_size': 147,
    'multi_stft_normalized': False, 'mlp_expansion_factor': 2, 'use_torch_checkpoint': False,
    'skip_connection': False,
}

# Ordem das saídas do modelo.
STEMS = ('accordion', 'acoustic-guitar', 'back-vocal', 'banjo', 'bass', 'bassoon', 'bells', 'bowed_strings', 'brass',
         'cello', 'clarinet', 'congas', 'digital-piano', 'dobro', 'double-bass', 'drums', 'electric-guitar', 'flute',
         'french-horn', 'glockenspiel', 'guitar', 'harmonica', 'harp', 'harpsichord', 'hh', 'keys', 'kick',
         'lead-vocal', 'mandolin', 'marimba', 'oboe', 'organ', 'percussion', 'piano', 'saxophone', 'sitar', 'snare',
         'strings', 'synth', 'tambourine', 'timpani', 'toms', 'triangle', 'trombone', 'trumpet', 'tuba', 'ukulele',
         'viola', 'violin', 'vocal', 'wind', 'wind-chimes', 'woodwind')

# Configuração de inferência do autor: trechos de 20 s. Numa GPU de 4 GB só cabem trechos de ~2 s (meia precisão).
TRECHO_AUTOR = 20.0

CHECKPOINT = {
    'arquivo': 'mega53-v1.ckpt', 'tamanho': 1368919887,
    'url': 'https://github.com/ZFTurbo/Music-Source-Separation-Training/releases/download/v1.0.21/'
           'mvsep_mega_model_bs_roformer_53_stems_v1.ckpt',
    'sha256': 'c62820893bbf86d4e734f966bd142d9157cfc8bb8e79e9d8f9ea553f3ff3519f',
}
BEAT_THIS = {
    'arquivo': 'beat_this-final0.ckpt', 'tamanho': 81058141,
    'url': 'https://cloud.cp.jku.at/public.php/dav/files/7ik4RrBKTS273gp/final0.ckpt',
    'sha256': '8c328b45f59d8dd3dff219253ff6a8d6482be57d0133a29140e2febbf8eb8331',
}
MODELOS = (CHECKPOINT, BEAT_THIS)

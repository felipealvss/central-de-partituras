"""Rede BS-RoFormer do modelo de separação (código de terceiros, MIT — ver LICENSE nesta pasta).

Revisado: só define a rede (PyTorch, einops, beartype, rotary-embedding-torch); não acessa rede, arquivos nem
processos. Os testes conferem isso por análise estática e fixam o hash dos arquivos (test_audio_trabalho.py);
nunca o importam. Só o trabalhador de áudio, no ambiente de áudio, carrega a rede.
"""

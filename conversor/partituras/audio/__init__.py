"""Modo de áudio: gravação → instrumento isolado → notas → parte transposta para o instrumento escolhido.

Os módulos leves (instrumentos, fonte, disponivel, mega53, baixar, trabalho) importam só a biblioteca padrão e
rodam no Python do servidor. Os pesados (separar, linha, ritmo, partitura, conferencia, avaliar) usam torch,
librosa e music21 e rodam só no ambiente de áudio (conversor/.venv-audio), pelo trabalhador da fila.
"""

"""Erros do conversor (nunca use sys.exit no núcleo: ele roda dentro de processos e do servidor)."""


class ErroConversao(Exception):
    """Falha esperada e explicável ao usuário (arquivo ausente, motor não instalado, limite de tempo...)."""


class Cancelado(ErroConversao):
    """A conversão foi cancelada pelo usuário."""

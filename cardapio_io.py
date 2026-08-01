# -*- coding: utf-8 -*-
"""Importação e exportação do pacote editável de cardápio."""

import copy
import json
from datetime import datetime, timezone


TIPO_PACOTE = "cardapio_marcela_editavel"
VERSAO_PACOTE = 1
TAMANHO_MAXIMO_BYTES = 10 * 1024 * 1024


def criar_pacote(resultado, slots, totais):
    """Cria uma cópia serializável do estado clínico e do cardápio em edição."""
    return {
        "tipo": TIPO_PACOTE,
        "versao": VERSAO_PACOTE,
        "criado_em": datetime.now(timezone.utc).isoformat(),
        "metas": copy.deepcopy(resultado.get("metas", {})),
        "slots": copy.deepcopy(slots),
        "totais": copy.deepcopy(totais),
        "anamnese": copy.deepcopy(resultado.get("anamnese", {})),
        "parametros": copy.deepcopy(resultado.get("parametros", {})),
        "excluidos": copy.deepcopy(resultado.get("excluidos", [])),
        "excluidos_usuario": copy.deepcopy(
            resultado.get("excluidos_usuario", [])
        ),
        "excluidos_regras": copy.deepcopy(
            resultado.get("excluidos_regras", [])
        ),
        "regras_ativas": copy.deepcopy(resultado.get("regras_ativas", [])),
        "avisos": copy.deepcopy(resultado.get("avisos", [])),
    }


def serializar_pacote(resultado, slots, totais):
    return json.dumps(
        criar_pacote(resultado, slots, totais),
        ensure_ascii=False,
        indent=2,
    )


def _validar_estrutura(pacote):
    if not isinstance(pacote, dict):
        raise ValueError("O arquivo precisa conter um objeto JSON.")
    if pacote.get("tipo") != TIPO_PACOTE:
        raise ValueError(
            "Arquivo incompatível. Importe o JSON editável exportado pelo app."
        )
    versao = pacote.get("versao")
    if versao != VERSAO_PACOTE:
        raise ValueError(
            f"Versão do arquivo não suportada: {versao!r}."
        )
    if not isinstance(pacote.get("metas"), dict):
        raise ValueError("O arquivo não contém metas nutricionais válidas.")
    if not isinstance(pacote.get("slots"), list) or not pacote["slots"]:
        raise ValueError("O arquivo não contém refeições válidas.")

    metas_obrigatorias = (
        "meta_kcal",
        "meta_carb_g",
        "meta_prot_g",
        "meta_gord_g",
    )
    ausentes = [chave for chave in metas_obrigatorias if chave not in pacote["metas"]]
    if ausentes:
        raise ValueError("Metas ausentes no arquivo: " + ", ".join(ausentes))

    for grupo in pacote["slots"]:
        if not isinstance(grupo, dict) or not isinstance(grupo.get("opcoes"), list):
            raise ValueError("Há uma refeição com estrutura inválida.")
        for opcao in grupo["opcoes"]:
            if not isinstance(opcao, dict) or not isinstance(
                opcao.get("alimentos"), list
            ):
                raise ValueError("Há uma opção de refeição inválida.")
            for alimento in opcao["alimentos"]:
                if not isinstance(alimento, dict):
                    raise ValueError("Há um alimento inválido no arquivo.")
                if "quantidade_g" not in alimento or "macros" not in alimento:
                    raise ValueError(
                        "Há um alimento sem gramatura ou macronutrientes."
                    )


def carregar_pacote(conteudo):
    """Lê bytes/texto JSON, valida o esquema e devolve uma cópia isolada."""
    if isinstance(conteudo, bytes):
        if len(conteudo) > TAMANHO_MAXIMO_BYTES:
            raise ValueError("O arquivo ultrapassa o limite de 10 MB.")
        try:
            conteudo = conteudo.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("O arquivo precisa estar em UTF-8.") from exc
    if not isinstance(conteudo, str):
        raise ValueError("Conteúdo de importação inválido.")
    if len(conteudo.encode("utf-8")) > TAMANHO_MAXIMO_BYTES:
        raise ValueError("O arquivo ultrapassa o limite de 10 MB.")
    try:
        pacote = json.loads(conteudo)
    except json.JSONDecodeError as exc:
        raise ValueError(f"JSON inválido: {exc.msg}.") from exc
    _validar_estrutura(pacote)
    return copy.deepcopy(pacote)

# -*- coding: utf-8 -*-
"""Regras clinicas deterministicas de apoio.

Este modulo nao diagnostica e nao prescreve. Ele cruza anamnese + cardapio com
regras editaveis em JSON para gerar alertas e filtros revisaveis.
"""

import json
import os
import unicodedata


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
REGRAS_PATH = os.path.join(BASE_DIR, "referencias", "regras", "regras_clinicas.json")

ORDEM_SEVERIDADE = {"baixa": 1, "media": 2, "alta": 3, "critica": 4}


def normalizar_texto(texto):
    if texto is None:
        return ""
    texto = str(texto).strip().lower()
    texto = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in texto if not unicodedata.combining(c))


def carregar_regras():
    with open(REGRAS_PATH, encoding="utf-8") as f:
        dados = json.load(f)
    return dados.get("regras", [])


def _lista(valor):
    if valor is None:
        return []
    if isinstance(valor, list):
        return [str(v).strip() for v in valor if str(v).strip()]
    return [v.strip() for v in str(valor).split(",") if v.strip()]


def _texto_campos(anamnese, campos):
    partes = []
    for campo in campos:
        valor = anamnese.get(campo)
        if isinstance(valor, dict):
            partes.extend(str(v) for v in valor.values() if v)
        elif isinstance(valor, list):
            partes.extend(str(v) for v in valor if v)
        elif valor:
            partes.append(str(valor))
    return normalizar_texto(" ".join(partes))


def _campo_texto(anamnese, campo):
    return _texto_campos(anamnese, [campo])


def _bate_algum(texto_norm, termos):
    return [t for t in termos if normalizar_texto(t) and normalizar_texto(t) in texto_norm]


def avaliar_anamnese(anamnese, regras=None):
    """Retorna regras ativas a partir dos campos estruturados da anamnese."""
    regras = regras or carregar_regras()
    anamnese = anamnese or {}
    ativas = []

    for regra in regras:
        detectados = []
        quando = regra.get("quando") or {}
        for campo, termos in quando.items():
            texto = _campo_texto(anamnese, campo)
            for termo in _bate_algum(texto, termos):
                detectados.append({"campo": campo, "termo": termo})
        if not detectados:
            continue
        item = dict(regra)
        item["detectado_por"] = detectados
        ativas.append(item)

    ativas.sort(key=lambda r: -ORDEM_SEVERIDADE.get(r.get("severidade", "baixa"), 1))
    return ativas


def termos_exclusao(anamnese, regras_ativas):
    """Termos que podem entrar nos filtros alimentares do motor."""
    termos = []
    for regra in regras_ativas or []:
        termos.extend(regra.get("termos_exclusao") or [])
        if regra.get("id") == "alergia_alimentar":
            termos.extend(_lista((anamnese or {}).get("alergias")))
    vistos = set()
    unicos = []
    for termo in termos:
        chave = normalizar_texto(termo)
        if not chave or chave in vistos:
            continue
        vistos.add(chave)
        unicos.append(str(termo).strip())
    return unicos


def resumo_regras(regras_ativas):
    return [
        {
            "id": r.get("id"),
            "titulo": r.get("titulo"),
            "severidade": r.get("severidade", "media"),
            "mensagem": r.get("mensagem", ""),
            "detectado_por": r.get("detectado_por", []),
        }
        for r in (regras_ativas or [])
    ]


def avaliar_cardapio(slots, regras_ativas, apenas_principais=True):
    """Varre o cardapio e retorna alertas por regra ativa."""
    alertas = []
    for regra in regras_ativas or []:
        termos_alerta = [normalizar_texto(t) for t in regra.get("alerta_alimentos", [])]
        termos_bloqueio = [normalizar_texto(t) for t in regra.get("bloqueio_alimentos", [])]
        if not termos_alerta and not termos_bloqueio:
            continue

        for grupo in slots or []:
            for opcao in grupo.get("opcoes", []):
                if apenas_principais and not opcao.get("conta_no_total"):
                    continue
                for alimento in opcao.get("alimentos", []):
                    if alimento.get("removido"):
                        continue
                    nome = alimento.get("nome_principal", "")
                    nome_norm = normalizar_texto(nome)
                    bloqueios = [t for t in termos_bloqueio if t and t in nome_norm]
                    avisos = [t for t in termos_alerta if t and t in nome_norm]
                    if not bloqueios and not avisos:
                        continue
                    nivel = "critica" if bloqueios else regra.get("severidade", "media")
                    alertas.append({
                        "severidade": nivel,
                        "regra_id": regra.get("id"),
                        "regra": regra.get("titulo"),
                        "refeicao": grupo.get("slot"),
                        "alimento": nome,
                        "termos": bloqueios or avisos,
                        "mensagem": regra.get("mensagem", ""),
                    })
    alertas.sort(key=lambda a: -ORDEM_SEVERIDADE.get(a.get("severidade", "baixa"), 1))
    return alertas

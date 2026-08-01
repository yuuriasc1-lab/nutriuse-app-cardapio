# -*- coding: utf-8 -*-
"""Modos de preparo curados e rascunhos de preparo por IA."""

import json
import os
import unicodedata

from ia_servico import carregar_prompt, gerar_json_gemini


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PREPAROS_PATH = os.path.join(BASE_DIR, "referencias", "preparos", "preparos_curados.json")


def normalizar_texto(texto):
    if texto is None:
        return ""
    texto = str(texto).strip().lower()
    texto = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in texto if not unicodedata.combining(c))


def carregar_preparos():
    if not os.path.exists(PREPAROS_PATH):
        return []
    with open(PREPAROS_PATH, encoding="utf-8") as f:
        dados = json.load(f)
    return dados.get("preparos", [])


def texto_opcao(opcao):
    nomes = [opcao.get("nome_refeicao", "")]
    nomes.extend(a.get("nome_principal", "") for a in opcao.get("alimentos", []))
    return normalizar_texto(" ".join(nomes))


def buscar_preparos(opcao, preparos=None):
    preparos = preparos or carregar_preparos()
    texto = texto_opcao(opcao)
    encontrados = []
    for preparo in preparos:
        termos = [normalizar_texto(t) for t in preparo.get("aplicar_quando", [])]
        if any(t and t in texto for t in termos):
            encontrados.append(preparo)
    return encontrados


def formatar_preparo_markdown(preparo, nivel_titulo="###"):
    linhas = [f"{nivel_titulo} {preparo.get('titulo', 'Modo de preparo')}"]
    if preparo.get("rascunho_ia"):
        linhas.append("_Rascunho gerado por IA para revisão._")
    modo = preparo.get("modo_preparo") or []
    for i, passo in enumerate(modo, start=1):
        linhas.append(f"{i}. {passo}")
    observacoes = preparo.get("observacoes") or []
    if observacoes:
        linhas.append("")
        linhas.append("Observações:")
        for obs in observacoes:
            linhas.append(f"- {obs}")
    return "\n".join(linhas)


def _resumo_alimentos(opcao):
    linhas = []
    for al in opcao.get("alimentos", []):
        if al.get("removido"):
            continue
        linhas.append(f"- {al.get('nome_principal', '')}: {al.get('quantidade_g', 0):.0f} g")
    return "\n".join(linhas)


def sugerir_preparo_ia(opcao, api_key, modelo=None, contexto_clinico=None):
    prompt_base = carregar_prompt("preparo.md")
    contexto = contexto_clinico or "Sem restricoes clinicas adicionais informadas."
    prompt = (
        f"{prompt_base}\n\n"
        f"### Contexto clinico\n{contexto}\n\n"
        f"### Refeicao\n{opcao.get('nome_refeicao', '')}\n\n"
        f"### Alimentos e porcoes\n{_resumo_alimentos(opcao)}\n"
    )
    dados = gerar_json_gemini(prompt, api_key=api_key, modelo=modelo or "gemini-2.5-flash")
    return {
        "id": "ia_" + normalizar_texto(opcao.get("nome_refeicao", "")).replace(" ", "_")[:40],
        "titulo": dados.get("titulo") or opcao.get("nome_refeicao", "Modo de preparo"),
        "modo_preparo": dados.get("modo_preparo") or [],
        "observacoes": dados.get("observacoes") or [],
        "rascunho_ia": True,
    }

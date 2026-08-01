# -*- coding: utf-8 -*-
"""Servicos pequenos para chamadas de IA usadas pelo app.

A IA deve devolver JSON estruturado. Calculos e regras clinicas continuam fora
do modelo generativo.
"""

import json
import os
import re


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROMPTS_DIR = os.path.join(BASE_DIR, "referencias", "prompts")


class ConfiguracaoIAError(Exception):
    """Erro de configuracao da IA: chave ausente, SDK ausente ou JSON invalido."""


def carregar_prompt(nome_arquivo):
    caminho = os.path.join(PROMPTS_DIR, nome_arquivo)
    with open(caminho, encoding="utf-8") as f:
        return f.read()


def parse_json_resposta(texto):
    """Faz json.loads tolerante, removendo cercas ```json quando aparecerem."""
    if not texto:
        raise ConfiguracaoIAError("A IA retornou resposta vazia.")
    limpo = texto.strip()
    limpo = re.sub(r"^```(?:json)?\s*|\s*```$", "", limpo, flags=re.IGNORECASE).strip()
    try:
        return json.loads(limpo)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", limpo, flags=re.DOTALL)
        if m:
            return json.loads(m.group(0))
        raise ConfiguracaoIAError("Não foi possível interpretar o JSON da IA.")


def gerar_json_gemini(prompt, api_key, modelo="gemini-2.5-flash"):
    """Executa uma chamada Gemini com temperatura 0 e resposta JSON."""
    try:
        from google import genai
        from google.genai import types
    except ImportError as e:
        raise ConfiguracaoIAError(
            "SDK do Gemini não instalada. Rode: pip install google-genai"
        ) from e

    if not api_key:
        raise ConfiguracaoIAError("Chave de API do Gemini não informada.")

    client = genai.Client(api_key=api_key)
    resposta = client.models.generate_content(
        model=modelo,
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0,
            response_mime_type="application/json",
        ),
    )
    return parse_json_resposta(resposta.text)

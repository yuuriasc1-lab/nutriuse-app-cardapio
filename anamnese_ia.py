# -*- coding: utf-8 -*-
"""
anamnese_ia.py — Leitura da anamnese (texto livre) -> dados estruturados
========================================================================

A nutricionista cola a anamnese preenchida (formato livre, como o
"DOCUMENTO PARA CRIAÇÃO DO CARDÁPIO.md") e a IA extrai os campos para um JSON
que alimenta o motor de cálculo.

Provedor padrão: Google Gemini (free tier) — cobre folgadamente ~20-30
cardápios/mês. O código é PLUGÁVEL: para trocar de provedor depois, basta
implementar outra função `_extrair_<provedor>` e referenciá-la em `PROVEDORES`.

Importante (segurança clínica, conforme a Documentação):
  - temperatura = 0  (cálculo/extração determinístico, evita "alucinação")
  - a IA NÃO inventa valores nutricionais; só LÊ o que a nutricionista escreveu.

Se não houver chave de API, `extrair_anamnese` levanta `ConfiguracaoIAError` e a
interface oferece o preenchimento manual do formulário.
"""

import json

from ia_servico import ConfiguracaoIAError, gerar_json_gemini, parse_json_resposta


# Esquema-alvo da extração. Documenta para a IA (e para nós) o formato de saída.
ESQUEMA_ANAMNESE = {
    "nome": "str | null",
    "idade": "int | null (anos)",
    "genero": "'Masculino' | 'Feminino' | null",
    "altura_cm": "float | null",
    "peso_atual_kg": "float | null",
    "peso_2anos_kg": "float | null",
    "peso_meta_kg": "float | null",
    "objetivo": "'Emagrecimento' | 'Hipertrofia' | 'Manutenção' | null",
    "atividade_fisica": "str | null (descrição livre)",
    "fator_atividade": "float entre 1.2 e 1.9 | null (estime pela descrição: "
                       "sedentário 1.2; leve 1.375; moderado 1.55; intenso 1.725; atleta 1.9)",
    "patologias": "lista de str (doenças relatadas)",
    "medicamentos": "lista de str",
    "exames_observacoes": "str | null (resumo dos exames relevantes)",
    "alergias": "lista de str",
    "intolerancias": "lista de str (ex: lactose, glúten)",
    "aversoes": "lista de str (alimentos que o paciente realmente NÃO come)",
    "preferencias": "lista de str (inegociáveis / que gosta e não abre mão)",
    "habito_intestinal": "str | null",
    "ingestao_hidrica_l": "float | null (litros/dia)",
    "consumo": {
        "refrigerante": "str | null",
        "alcool": "str | null",
        "sucos": "str | null",
        "doces": "str | null",
        "frituras": "str | null",
    },
    "tabagismo": "bool | null",
    "rotina_alimentar": "lista de objetos {refeicao, horario, descricao} "
                        "(o que o paciente come hoje)",
}

PROMPT_SISTEMA = (
    "Você é um assistente de extração de dados clínicos para uma nutricionista. "
    "Receberá o texto livre de uma ANAMNESE e deve extrair EXCLUSIVAMENTE as "
    "informações presentes no texto, sem inventar nem estimar valores que não "
    "estejam escritos (exceto o campo 'fator_atividade', que você pode inferir "
    "a partir da descrição da atividade física). "
    "Quando um campo não aparecer no texto, retorne null (ou lista vazia). "
    "Responda SOMENTE com um objeto JSON válido, sem comentários, seguindo "
    "exatamente as chaves especificadas."
)


def _montar_prompt(texto_anamnese):
    esquema_str = json.dumps(ESQUEMA_ANAMNESE, ensure_ascii=False, indent=2)
    return (
        f"{PROMPT_SISTEMA}\n\n"
        f"### Esquema de saída (chaves e tipos esperados)\n{esquema_str}\n\n"
        f"### Texto da anamnese\n{texto_anamnese}\n\n"
        f"### Saída\nRetorne apenas o JSON."
    )


# ---------------------------------------------------------------------------
# Provedor: Google Gemini
# ---------------------------------------------------------------------------

def _extrair_gemini(texto_anamnese, api_key, modelo="gemini-2.5-flash"):
    """Extrai a anamnese usando a API do Google Gemini (free tier)."""
    return gerar_json_gemini(_montar_prompt(texto_anamnese), api_key, modelo)


# Registro de provedores disponíveis (extensível: openai, groq, etc.).
PROVEDORES = {
    "gemini": _extrair_gemini,
}


def _parse_json_resposta(texto):
    """Faz json.loads tolerante (remove cercas de código se vierem)."""
    return parse_json_resposta(texto)


def extrair_anamnese(texto_anamnese, api_key, provedor="gemini", modelo=None):
    """Extrai a anamnese para dicionário estruturado usando o provedor escolhido.

    Levanta ConfiguracaoIAError em caso de problema de configuração.
    """
    if not texto_anamnese or not texto_anamnese.strip():
        raise ValueError("Texto da anamnese vazio.")
    func = PROVEDORES.get(provedor)
    if func is None:
        raise ConfiguracaoIAError(f"Provedor de IA não suportado: {provedor}")
    kwargs = {"api_key": api_key}
    if modelo:
        kwargs["modelo"] = modelo
    dados = func(texto_anamnese, **kwargs)
    return normalizar_anamnese(dados)


# ---------------------------------------------------------------------------
# Normalização do resultado (garante todas as chaves, tipos seguros)
# ---------------------------------------------------------------------------

def normalizar_anamnese(dados):
    """Garante que o dicionário tenha todas as chaves esperadas com tipos seguros."""
    d = dados or {}

    def _lista(v):
        if v is None:
            return []
        if isinstance(v, list):
            return [str(x).strip() for x in v if str(x).strip()]
        return [s.strip() for s in str(v).split(",") if s.strip()]

    consumo = d.get("consumo") or {}
    return {
        "nome": d.get("nome"),
        "idade": d.get("idade"),
        "genero": d.get("genero"),
        "altura_cm": d.get("altura_cm"),
        "peso_atual_kg": d.get("peso_atual_kg"),
        "peso_2anos_kg": d.get("peso_2anos_kg"),
        "peso_meta_kg": d.get("peso_meta_kg"),
        "objetivo": d.get("objetivo"),
        "atividade_fisica": d.get("atividade_fisica"),
        "fator_atividade": d.get("fator_atividade"),
        "patologias": _lista(d.get("patologias")),
        "medicamentos": _lista(d.get("medicamentos")),
        "exames_observacoes": d.get("exames_observacoes"),
        "alergias": _lista(d.get("alergias")),
        "intolerancias": _lista(d.get("intolerancias")),
        "aversoes": _lista(d.get("aversoes")),
        "preferencias": _lista(d.get("preferencias")),
        "habito_intestinal": d.get("habito_intestinal"),
        "ingestao_hidrica_l": d.get("ingestao_hidrica_l"),
        "consumo": {
            "refrigerante": consumo.get("refrigerante"),
            "alcool": consumo.get("alcool"),
            "sucos": consumo.get("sucos"),
            "doces": consumo.get("doces"),
            "frituras": consumo.get("frituras"),
        },
        "tabagismo": d.get("tabagismo"),
        "rotina_alimentar": d.get("rotina_alimentar") or [],
    }


def anamnese_vazia():
    """Retorna uma anamnese 'em branco' para preenchimento manual (sem IA)."""
    return normalizar_anamnese({})

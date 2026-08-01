# -*- coding: utf-8 -*-
"""
comando_ia.py — Interpreta comandos em texto livre da nutricionista
===================================================================

A Marcela digita uma instrução em linguagem natural sobre o cardápio já
gerado (ex.: "troca o arroz do almoço por batata doce", "tira o mamão do
café", "põe 1 ovo no lanche da tarde") e a IA traduz isso para OPERAÇÕES
ESTRUTURADAS que o app aplica usando o motor determinístico.

Filosofia (igual à da anamnese, conforme a Documentação, seção 4.2):
  - temperatura = 0  (interpretação determinística, sem "alucinação");
  - a IA NÃO inventa valores nutricionais nem gramaturas: ela só identifica a
    INTENÇÃO (ação + alimento + refeição). Quem calcula é o motor.py.

Provedor padrão: Google Gemini — reaproveita o cliente e o parser tolerante de
JSON já usados em anamnese_ia.py.
"""

import json

from anamnese_ia import ConfiguracaoIAError
from ia_servico import gerar_json_gemini


# Ações suportadas (fase 1: trocar/remover/adicionar; fase 2: ajustar).
ACOES_SUPORTADAS = ("trocar", "remover", "adicionar", "ajustar")

# Valores canônicos dos campos de 'ajustar'.
MACROS_VALIDOS = ("proteina", "carboidrato", "gordura", "calorias")
MODOS_VALIDOS = ("aumentar", "diminuir", "definir")
UNIDADES_VALIDAS = ("g", "%", "x")

ESQUEMA_COMANDO = {
    "operacoes": [
        {
            "acao": "'trocar' | 'remover' | 'adicionar' | 'ajustar'",
            "refeicao": "str | null (nome da refeição/horário EXATAMENTE como "
                        "aparece na lista de contexto; null se o comando não "
                        "especificar a refeição)",
            "alimento": "str | null (trocar/remover: o alimento alvo já presente "
                        "no cardápio; adicionar: o alimento a incluir; ajustar: "
                        "o alimento cuja QUANTIDADE muda — null quando o ajuste "
                        "for de um MACRO da refeição inteira)",
            "substituto": "str | null (somente para 'trocar': o novo alimento)",
            "quantidade_g": "número | null (somente para 'adicionar', se a "
                            "nutricionista informar a quantidade em gramas)",
            "macro": "'proteina'|'carboidrato'|'gordura'|'calorias'|null "
                     "(somente para 'ajustar' um macro da refeição inteira; "
                     "null quando o ajuste for da quantidade de um alimento)",
            "modo": "'aumentar'|'diminuir'|'definir'|null (somente para 'ajustar')",
            "valor": "número|null (quanto ajustar — ver 'unidade')",
            "unidade": "'g'|'%'|'x'|null (para 'ajustar': g=gramas; %=percentual "
                       "sobre o valor atual; x=multiplicador, ex.: 'dobrar'=2x, "
                       "'metade'=0.5x com modo 'definir')",
        }
    ],
    "comentario": "str (resumo curto do que você entendeu; se o comando estiver "
                  "ambíguo ou impossível, explique aqui em vez de adivinhar)",
}

PROMPT_SISTEMA = (
    "Você é um assistente que traduz comandos de uma NUTRICIONISTA sobre um "
    "cardápio já montado para operações estruturadas de edição. "
    "As ações permitidas são: 'trocar' (substituir um alimento por outro), "
    "'remover' (tirar um alimento), 'adicionar' (incluir um alimento novo numa "
    "refeição) e 'ajustar' (mudar uma quantidade ou um macronutriente). "
    "NÃO invente valores nutricionais nem gramaturas — apenas identifique a "
    "intenção. O cálculo é feito por outro sistema. "
    "Use SEMPRE o nome da refeição exatamente como aparece na lista de contexto "
    "fornecida; se o comando não disser a refeição, deixe 'refeicao' como null. "
    "Para o alimento alvo de 'trocar'/'remover', use o nome do alimento como "
    "ele aparece no cardápio. "
    "Para 'ajustar': se mudar a quantidade de UM alimento (ex.: 'aumenta o arroz "
    "para 100g', 'diminui a aveia pela metade'), preencha 'alimento', 'modo', "
    "'valor' e 'unidade' e deixe 'macro' null. Se ajustar um MACRO da refeição "
    "inteira (ex.: 'aumenta a proteína do jantar em 20g'), preencha 'macro', "
    "'refeicao', 'modo', 'valor' e 'unidade' e deixe 'alimento' null. "
    "'dobrar'=modo 'definir', valor 2, unidade 'x'; 'pela metade'=modo 'definir', "
    "valor 0.5, unidade 'x'. "
    "Um único comando pode conter várias operações (ex.: tirar um e pôr outro). "
    "Responda SOMENTE com um objeto JSON válido seguindo o esquema."
)


def _montar_prompt(comando, contexto_cardapio):
    esquema_str = json.dumps(ESQUEMA_COMANDO, ensure_ascii=False, indent=2)
    return (
        f"{PROMPT_SISTEMA}\n\n"
        f"### Esquema de saída\n{esquema_str}\n\n"
        f"### Cardápio atual (refeições e alimentos disponíveis)\n"
        f"{contexto_cardapio}\n\n"
        f"### Comando da nutricionista\n{comando}\n\n"
        f"### Saída\nRetorne apenas o JSON."
    )


def _interpretar_gemini(comando, contexto_cardapio, api_key, modelo="gemini-2.5-flash"):
    return gerar_json_gemini(_montar_prompt(comando, contexto_cardapio), api_key, modelo)


PROVEDORES = {
    "gemini": _interpretar_gemini,
}


def interpretar_comando(comando, contexto_cardapio, api_key, provedor="gemini", modelo=None):
    """Traduz um comando em texto livre para operações estruturadas.

    Retorna {"operacoes": [...], "comentario": str}. Levanta ConfiguracaoIAError
    em problema de configuração e ValueError se o comando vier vazio.
    """
    if not comando or not comando.strip():
        raise ValueError("Comando vazio.")
    func = PROVEDORES.get(provedor)
    if func is None:
        raise ConfiguracaoIAError(f"Provedor de IA não suportado: {provedor}")
    kwargs = {"api_key": api_key}
    if modelo:
        kwargs["modelo"] = modelo
    dados = func(comando, contexto_cardapio, **kwargs)
    return _normalizar(dados)


def _normalizar(dados):
    """Garante a forma esperada e descarta operações com ação inválida."""
    d = dados or {}
    ops = []
    for op in d.get("operacoes") or []:
        acao = str(op.get("acao", "")).strip().lower()
        if acao not in ACOES_SUPORTADAS:
            continue
        ops.append({
            "acao": acao,
            "refeicao": (op.get("refeicao") or None),
            "alimento": (op.get("alimento") or "").strip() or None,
            "substituto": (op.get("substituto") or None),
            "quantidade_g": _num(op.get("quantidade_g")),
            "macro": _enum(op.get("macro"), MACROS_VALIDOS),
            "modo": _enum(op.get("modo"), MODOS_VALIDOS),
            "valor": _num(op.get("valor")),
            "unidade": _enum(op.get("unidade"), UNIDADES_VALIDAS),
        })
    return {"operacoes": ops, "comentario": (d.get("comentario") or "").strip()}


def _num(v):
    """Converte para float ou None (tolerante a '20g', '1,5')."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    texto = str(v).strip().replace(",", ".")
    import re as _re
    m = _re.search(r"-?\d+(?:\.\d+)?", texto)
    return float(m.group(0)) if m else None


def _enum(v, validos):
    """Normaliza um campo enum (minúsculo, sem acento); None se fora do conjunto."""
    if not v:
        return None
    import unicodedata
    t = "".join(c for c in unicodedata.normalize("NFKD", str(v).strip().lower())
                if not unicodedata.combining(c))
    # sinônimos comuns
    sin = {"proteinas": "proteina", "protein": "proteina", "prot": "proteina",
           "carboidratos": "carboidrato", "carbo": "carboidrato", "carb": "carboidrato",
           "gorduras": "gordura", "lipidio": "gordura", "lipidios": "gordura",
           "caloria": "calorias", "kcal": "calorias", "cal": "calorias"}
    t = sin.get(t, t)
    return t if t in validos else None

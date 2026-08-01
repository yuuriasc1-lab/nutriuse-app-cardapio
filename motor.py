# -*- coding: utf-8 -*-
"""
motor.py — Motor de cálculo clínico e geração do cardápio
==========================================================

Lógica pura (sem Streamlit e sem IA):

    1. TMB (Harris-Benedict revisada, 1984)
    2. GET = TMB × Fator de Atividade Física (FAF)
    3. Tetos exatos de kcal, carboidrato, proteína e gordura definidos pela
       nutricionista
    4. Geração a partir do cardápio-base da Marcela, preservando seus alimentos,
       refeições e opções
    5. Otimização conjunta das porções, sem ultrapassar nenhum dos quatro tetos
    6. TBCA usada somente como apoio em substituições pontuais

As quantidades profissionais mantêm precisão decimal de 0,1 g. A apresentação
ao paciente usa valores inteiros arredondados para baixo. Alterar uma porção
reescala de forma proporcional suas calorias e seus macronutrientes.
"""

import json
import math
import os
import re
import unicodedata


# ---------------------------------------------------------------------------
# CONSTANTES
# ---------------------------------------------------------------------------

DIRETORIO_BASE = os.path.dirname(os.path.abspath(__file__))

DIR_REFERENCIAS = os.path.join(DIRETORIO_BASE, "referencias")
DIR_CARDAPIO = os.path.join(DIR_REFERENCIAS, "cardapio")
DIR_ALIMENTOS = os.path.join(DIR_REFERENCIAS, "alimentos")

ARQUIVOS_TEMPLATE = [
    os.path.join("referencias", "cardapio", "cardapio_base.json"),
    os.path.join("referencias", "cardapio", "template_base.json"),
    "cardapio_base.json",
    "template_base.json",
]
ARQUIVOS_ALIMENTOS = [
    os.path.join("referencias", "alimentos", "alimentos.json"),
    os.path.join("referencias", "alimentos", "tbca_alimentos.json"),
    "alimentos.json",
    "tbca_alimentos.json",
]

# Ajuste legado/sugerido por objetivo. A interface atual usa meta kcal manual.
AJUSTE_OBJETIVO_PADRAO = {
    "Emagrecimento": -400,
    "Manutenção": 0,
    "Hipertrofia": +400,
}

# Proteína (g/kg) padrão por objetivo — Regra de Ouro do documento.
PROTEINA_G_KG_PADRAO = {
    "Emagrecimento": 2.0,   # preserva massa magra em déficit
    "Manutenção": 1.6,
    "Hipertrofia": 2.0,
}

# % de gordura sobre as calorias totais (padrão 25%).
PERC_GORDURA_PADRAO = 0.25

# De-para classe TBCA (alimentos.json) -> categoria simplificada do template.
MAPA_CLASSE_PARA_CATEGORIA = {
    "Cereais e derivados": "Carboidrato",
    "Frutas e derivados": "Carboidrato",
    "Leguminosas e derivados": "Carboidrato",
    "Produtos açucarados": "Carboidrato",
    "Açúcares e doces": "Carboidrato",
    "Vegetais e derivados": "Carboidrato",
    "Carnes e derivados": "Proteína",
    "Pescados e Frutos do mar": "Proteína",
    "Pescados e frutos do mar": "Proteína",
    "Ovos e derivados": "Proteína",
    "Leite e derivados": "Proteína",
    "Gorduras e óleos": "Gordura",
    "Sementes e Oleaginosas": "Gordura",
}

# Macronutriente principal de cada categoria.
MACRO_PRINCIPAL = {
    "Carboidrato": "carboidratos_g",
    "Proteína": "proteinas_g",
    "Gordura": "gorduras_g",
}

# Chave equivalente no banco TBCA normalizado.
MACRO_PARA_CHAVE_TBCA = {
    "carboidratos_g": "carboidrato",
    "proteinas_g": "proteina",
    "gorduras_g": "lipidios",
}

ROTULO_MACRO = {
    "carboidratos_g": "carboidrato",
    "proteinas_g": "proteina",
    "gorduras_g": "gordura",
}

# Faixas simples para evitar substituicoes com porcoes clinicamente ruins.
# Valores fora da faixa ideal ainda podem aparecer, mas perdem score e saem
# marcados com alerta para revisao humana.
PORCAO_IDEAL_G = {
    "Carboidrato": (30, 300),
    "Proteína": (40, 250),
    "Gordura": (5, 60),
}

PORCAO_MAXIMA_G = {
    "Carboidrato": 500,
    "Proteína": 400,
    "Gordura": 120,
}

TERMOS_PRATO_COMPOSTO = (
    "molho", "sopa", "sanduiche", "pizza", "torta", "lasanha", "risoto",
    "panqueca", "estrogonofe", "feijoada", "yakisoba", "coxinha", "pastel",
    "bolo", "nugget", "hamburguer",
)

TERMOS_ULTRAPROCESSADO = (
    "refrigerante", "achocolatado", "biscoito", "bolacha recheada",
    "salgadinho", "sorvete", "pudim", "chocolate", "salsicha", "mortadela",
    "presunto", "empanado",
)

TERMOS_ACUCAR_ADICIONADO = ("acucar", "adocad", "mel", "geleia")
TERMOS_BEBIDA = ("suco", "refresco", "nectar", "bebida")
TERMOS_INGREDIENTE_BRUTO = ("fecula", "polvilho", "amido", "farinha")
TERMOS_FRUTA_SECA = ("seca", "desidrat", "passa")
TERMOS_PARTE_NAO_USUAL = ("casca", "semente", "caroco", "talos", "folha")
TERMOS_PREPARO_FRUTA_PENALIZADO = ("cozid", "conserva", "calda", "cristaliz")

FRUTAS_COMUNS = (
    "mamao", "maca", "pera", "laranja", "morango", "abacaxi", "manga",
    "uva", "melancia", "melao", "kiwi",
)

FRUTAS = (
    "banana", "mamao", "maca", "pera", "laranja", "morango", "abacaxi",
    "manga", "uva", "melancia", "melao", "kiwi", "fruta",
)

AMIDOS = (
    "arroz", "feijao", "batata", "mandioca", "macarrao", "pao", "aveia",
    "tapioca", "cuscuz", "milho", "abobora", "torrada", "bolacha de arroz",
)

PROTEINAS = (
    "frango", "patinho", "carne", "ovo", "clara", "tilapia", "peixe",
    "atum", "whey", "iogurte", "queijo", "ricota", "cottage", "leite",
)

GORDURAS = (
    "azeite", "castanha", "amendoa", "nozes", "abacate", "chia", "linhaca",
    "pasta de amendoim",
)

CLASSES_CAUTELA = ("produtos acucarados", "acucares e doces")


# ---------------------------------------------------------------------------
# UTILITÁRIOS
# ---------------------------------------------------------------------------

def normalizar_texto(texto):
    """Minúsculas, sem acento, sem espaços extras — para comparar nomes."""
    if texto is None:
        return ""
    texto = str(texto).strip().lower()
    texto = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in texto if not unicodedata.combining(c))


def eh_salada_ou_legume(alimento_ou_nome):
    """Identifica saladas/vegetais que podem receber orientação textual."""
    if isinstance(alimento_ou_nome, dict):
        nome = alimento_ou_nome.get("nome_principal", "")
    else:
        nome = alimento_ou_nome or ""
    nome_norm = normalizar_texto(nome)
    if "fruta" in nome_norm:
        return False
    return any(
        termo in nome_norm
        for termo in ("salada", "legume", "folha", "verdura", "vegetais")
    )


def normalizar_alimento_livre(alimento):
    """Migra itens livres antigos e define a orientação padrão da Marcela."""
    novo = dict(alimento)
    nome = str(novo.get("nome_principal", "") or "")
    nome_norm = normalizar_texto(nome)
    if nome_norm.startswith("legumes (minimo") and ")" not in nome:
        novo["nome_principal"] = "Legumes"
        novo.setdefault("orientacao_paciente", "À vontade (mínimo 100 g)")

    macros = novo.get("macros") or {}
    sem_nutrientes = not any([
        float(novo.get("calorias", 0) or 0),
        *(float(macros.get(chave, 0) or 0) for chave in (
            "carboidratos_g", "proteinas_g", "gorduras_g"
        )),
    ])
    if eh_salada_ou_legume(novo) and sem_nutrientes:
        novo.setdefault("orientacao_paciente", "À vontade")
    return novo


def numero_br_para_float(valor):
    """Converte '23,1' / 'NA' / 'Tr' -> float (0.0 quando inválido/ausente)."""
    if valor is None:
        return 0.0
    texto = str(valor).strip()
    if texto in ("", "NA", "Tr", "tr", "*", "-"):
        return 0.0
    texto = texto.replace(".", "").replace(",", ".") if "," in texto else texto
    try:
        return float(texto)
    except ValueError:
        return 0.0


def _primeiro_arquivo(nomes):
    for nome in nomes:
        caminho = os.path.join(DIRETORIO_BASE, nome)
        if os.path.exists(caminho):
            return caminho
    return None


# ---------------------------------------------------------------------------
# CARREGAMENTO DE DADOS
# ---------------------------------------------------------------------------

def carregar_template():
    """Carrega o cardápio base. Lança FileNotFoundError/ValueError em erro."""
    caminho = _primeiro_arquivo(ARQUIVOS_TEMPLATE)
    if caminho is None:
        raise FileNotFoundError(
            f"Cardápio base não encontrado ({', '.join(ARQUIVOS_TEMPLATE)})."
        )
    with open(caminho, "r", encoding="utf-8") as f:
        dados = json.load(f)
    calorias = dados.get("calorias_totais_estimadas") or dados.get("calorias_totais") or 0
    refeicoes = []
    for refeicao in dados.get("refeicoes", []):
        refeicao_normalizada = dict(refeicao)
        refeicao_normalizada["alimentos"] = [
            normalizar_alimento_livre(alimento)
            for alimento in refeicao.get("alimentos", [])
        ]
        refeicoes.append(refeicao_normalizada)
    return {
        "nome": dados.get("nome_template", "Cardápio Base"),
        "calorias_totais": float(calorias),
        "refeicoes": refeicoes,
    }


def carregar_banco_alimentos():
    """Carrega e normaliza o banco TBCA. Lança FileNotFoundError em erro."""
    caminho = _primeiro_arquivo(ARQUIVOS_ALIMENTOS)
    if caminho is None:
        raise FileNotFoundError(
            f"Banco de alimentos não encontrado ({', '.join(ARQUIVOS_ALIMENTOS)})."
        )
    with open(caminho, "r", encoding="utf-8") as f:
        dados = json.load(f)

    alimentos = []
    for item in dados:
        if "energia_kcal" in item or "nome_alimento" in item:
            classe = item.get("categoria") or item.get("classe", "")
            alimentos.append({
                "nome_alimento": item.get("nome_alimento") or item.get("descricao", ""),
                "classe": classe,
                "categoria": MAPA_CLASSE_PARA_CATEGORIA.get(classe, item.get("categoria", "Outro")),
                "energia_kcal": numero_br_para_float(item.get("energia_kcal")),
                "carboidrato": numero_br_para_float(item.get("carboidrato")),
                "proteina": numero_br_para_float(item.get("proteina")),
                "lipidios": numero_br_para_float(item.get("lipidios")),
            })
            continue
        valores = _extrair_macros_tbca(item.get("nutrientes", []))
        classe = item.get("classe", "")
        alimentos.append({
            "nome_alimento": item.get("descricao", "").strip().rstrip(","),
            "classe": classe,
            "categoria": MAPA_CLASSE_PARA_CATEGORIA.get(classe, "Outro"),
            "energia_kcal": valores["kcal"],
            "carboidrato": valores["carboidrato"],
            "proteina": valores["proteina"],
            "lipidios": valores["lipidios"],
        })
    return alimentos


def _extrair_macros_tbca(nutrientes):
    res = {"kcal": 0.0, "carboidrato": 0.0, "proteina": 0.0, "lipidios": 0.0}
    for n in nutrientes:
        comp = normalizar_texto(n.get("Componente", ""))
        uni = normalizar_texto(n.get("Unidades", ""))
        val = numero_br_para_float(n.get("Valor por 100g"))
        if comp == "energia" and uni == "kcal":
            res["kcal"] = val
        elif comp == "carboidrato disponivel" and res["carboidrato"] == 0:
            res["carboidrato"] = val
        elif comp == "carboidrato total" and res["carboidrato"] == 0:
            res["carboidrato"] = val
        elif comp == "proteina":
            res["proteina"] = val
        elif comp == "lipidios":
            res["lipidios"] = val
    return res


# ---------------------------------------------------------------------------
# 1. CÁLCULO METABÓLICO E METAS DE MACRO
# ---------------------------------------------------------------------------

def calcular_tmb(peso_kg, altura_cm, idade, genero):
    """TMB por Harris-Benedict revisada (1984)."""
    if normalizar_texto(genero) == "masculino":
        return 88.362 + (13.397 * peso_kg) + (4.799 * altura_cm) - (5.677 * idade)
    return 447.593 + (9.247 * peso_kg) + (3.098 * altura_cm) - (4.330 * idade)


KCAL_POR_GRAMA_META = {
    "meta_prot_g": 4.0,
    "meta_carb_g": 4.0,
    "meta_gord_g": 9.0,
}
DISTRIBUICAO_ENERGETICA_PADRAO = {
    "meta_prot_g": 0.25,
    "meta_carb_g": 0.50,
    "meta_gord_g": 0.25,
}


def calorias_dos_macros(proteina_g, carboidrato_g, gordura_g):
    """Calcula energia pelos fatores de Atwater (4/4/9)."""
    return (
        4.0 * max(float(proteina_g or 0), 0.0)
        + 4.0 * max(float(carboidrato_g or 0), 0.0)
        + 9.0 * max(float(gordura_g or 0), 0.0)
    )


def _piso_decimo(valor):
    """Uma casa decimal sem arredondar para cima."""
    return math.floor(max(float(valor or 0), 0.0) * 10 + 1e-9) / 10.0


def _ajustar_decimos_ao_teto(ideais, alvo_kcal, ajustaveis):
    """Escolhe os décimos mais próximos sem ultrapassar o teto energético."""
    ajustaveis = tuple(ajustaveis)
    base = {
        chave: (
            _piso_decimo(valor)
            if chave in ajustaveis
            else round(max(float(valor or 0), 0.0), 1)
        )
        for chave, valor in ideais.items()
    }
    melhor = dict(base)
    melhor_objetivo = None
    for mascara in range(1 << len(ajustaveis)):
        candidato = dict(base)
        for indice, chave in enumerate(ajustaveis):
            if mascara & (1 << indice):
                candidato[chave] = round(candidato[chave] + 0.1, 1)
        energia = sum(
            candidato[chave] * KCAL_POR_GRAMA_META[chave]
            for chave in KCAL_POR_GRAMA_META
        )
        if energia > alvo_kcal + 1e-9:
            continue
        erro_distribuicao = sum(
            (
                (candidato[chave] - ideais[chave])
                * KCAL_POR_GRAMA_META[chave]
            ) ** 2
            for chave in KCAL_POR_GRAMA_META
        )
        objetivo = (round(alvo_kcal - energia, 9), erro_distribuicao)
        if melhor_objetivo is None or objetivo < melhor_objetivo:
            melhor = candidato
            melhor_objetivo = objetivo
    return melhor


def readequar_metas_macros(meta_kcal, proteina_g, carboidrato_g, gordura_g,
                           ancora="meta_kcal"):
    """Readequa macros de forma reativa sem exceder a meta calórica.

    Quando a âncora é `meta_kcal`, os três macros são escalados mantendo a
    distribuição energética atual. Quando a âncora é um macro, esse valor é
    preservado e a energia restante é redistribuída entre os outros dois na
    proporção vigente. Os valores derivados usam uma casa decimal para baixo,
    portanto a energia dos macros nunca ultrapassa `meta_kcal`.
    """
    if ancora not in {"meta_kcal", *KCAL_POR_GRAMA_META}:
        raise ValueError(f"Âncora de readequação inválida: {ancora!r}.")

    alvo_kcal = max(float(meta_kcal or 0), 0.0)
    valores = {
        "meta_prot_g": max(float(proteina_g or 0), 0.0),
        "meta_carb_g": max(float(carboidrato_g or 0), 0.0),
        "meta_gord_g": max(float(gordura_g or 0), 0.0),
    }
    limitado = False
    mensagem = ""

    if ancora == "meta_kcal":
        energia_atual = sum(
            valores[chave] * fator
            for chave, fator in KCAL_POR_GRAMA_META.items()
        )
        if energia_atual > 0:
            ideais = {
                chave: valor * alvo_kcal / energia_atual
                for chave, valor in valores.items()
            }
        else:
            ideais = {
                chave: (
                    alvo_kcal
                    * DISTRIBUICAO_ENERGETICA_PADRAO[chave]
                    / KCAL_POR_GRAMA_META[chave]
                )
                for chave in KCAL_POR_GRAMA_META
            }
        ajustados = _ajustar_decimos_ao_teto(
            ideais, alvo_kcal, KCAL_POR_GRAMA_META
        )
    else:
        fator_ancora = KCAL_POR_GRAMA_META[ancora]
        solicitado = round(valores[ancora], 1)
        maximo_ancora = _piso_decimo(alvo_kcal / fator_ancora)
        valor_ancora = min(solicitado, maximo_ancora)
        limitado = valor_ancora < solicitado - 1e-9
        energia_restante = max(
            alvo_kcal - (valor_ancora * fator_ancora), 0.0
        )
        outras = [chave for chave in KCAL_POR_GRAMA_META if chave != ancora]
        energia_outros = sum(
            valores[chave] * KCAL_POR_GRAMA_META[chave]
            for chave in outras
        )
        if energia_outros > 0:
            pesos = {
                chave: (
                    valores[chave] * KCAL_POR_GRAMA_META[chave]
                    / energia_outros
                )
                for chave in outras
            }
        else:
            soma_padrao = sum(
                DISTRIBUICAO_ENERGETICA_PADRAO[chave]
                for chave in outras
            )
            pesos = {
                chave: DISTRIBUICAO_ENERGETICA_PADRAO[chave] / soma_padrao
                for chave in outras
            }
        ideais = {ancora: valor_ancora}
        for chave in outras:
            ideais[chave] = (
                energia_restante * pesos[chave]
                / KCAL_POR_GRAMA_META[chave]
            )
        ajustados = _ajustar_decimos_ao_teto(
            ideais, alvo_kcal, outras
        )
        if limitado:
            rotulos = {
                "meta_prot_g": "Proteína",
                "meta_carb_g": "Carboidrato",
                "meta_gord_g": "Gordura",
            }
            mensagem = (
                f"{rotulos[ancora]} limitada a {valor_ancora:.1f} g: "
                "um valor maior ultrapassaria sozinho o limite calórico."
            )

    return {
        **ajustados,
        "kcal_macros": round(calorias_dos_macros(
            ajustados["meta_prot_g"],
            ajustados["meta_carb_g"],
            ajustados["meta_gord_g"],
        ), 1),
        "limitado": limitado,
        "mensagem": mensagem,
    }


def calcular_metas(peso_kg, altura_cm, idade, genero, fator_atividade, objetivo,
                   ajuste_kcal=None, prot_g_kg=None, perc_gordura=PERC_GORDURA_PADRAO,
                   meta_kcal_manual=None, meta_prot_g_manual=None,
                   meta_carb_g_manual=None, meta_gord_g_manual=None):
    """Calcula TMB, GET, meta calórica e metas de macro.

    A meta calórica pode ser definida diretamente pela nutricionista. Quando
    `meta_kcal_manual` não é informado, o cálculo legado usa GET + ajuste_kcal.
    As metas de proteína, carboidrato e gordura também podem ser informadas
    diretamente em gramas. Sem valores manuais, são usadas as sugestões por
    g/kg, percentual de gordura e carboidrato residual.

    Retorna um dicionário com todos os valores calculados.
    """
    if prot_g_kg is None:
        prot_g_kg = PROTEINA_G_KG_PADRAO.get(objetivo, 1.6)

    tmb = calcular_tmb(peso_kg, altura_cm, idade, genero)
    get = tmb * fator_atividade
    if meta_kcal_manual is None:
        if ajuste_kcal is None:
            ajuste_kcal = AJUSTE_OBJETIVO_PADRAO.get(objetivo, 0)
        meta_kcal = get + ajuste_kcal
    else:
        meta_kcal = float(meta_kcal_manual)
        ajuste_kcal = meta_kcal - get

    # Regras de Ouro: proteína ancorada por kg -> gordura por % -> carbo restante.
    prot_sugerida_g = prot_g_kg * peso_kg
    gord_sugerida_g = (perc_gordura * meta_kcal) / 9.0
    kcal_restante = meta_kcal - (prot_sugerida_g * 4) - (gord_sugerida_g * 9)
    carb_sugerido_g = max(kcal_restante, 0) / 4.0

    prot_g = (prot_sugerida_g if meta_prot_g_manual is None
              else max(float(meta_prot_g_manual), 0.0))
    carb_g = (carb_sugerido_g if meta_carb_g_manual is None
              else max(float(meta_carb_g_manual), 0.0))
    gord_g = (gord_sugerida_g if meta_gord_g_manual is None
              else max(float(meta_gord_g_manual), 0.0))
    fibra_g = (meta_kcal / 1000.0) * 14.0
    kcal_macros = (4 * carb_g) + (4 * prot_g) + (9 * gord_g)
    prot_g_kg_real = prot_g / peso_kg if peso_kg else 0.0
    perc_gordura_real = (gord_g * 9 / meta_kcal) if meta_kcal else 0.0

    return {
        "formula_tmb": "Harris-Benedict revisada (1984)",
        "tmb": round(tmb),
        "get": round(get),
        "ajuste_kcal": round(ajuste_kcal),
        "meta_kcal": round(meta_kcal),
        "prot_g_kg": round(prot_g_kg_real, 3),
        "perc_gordura": round(perc_gordura_real, 4),
        "meta_prot_g": round(prot_g, 1),
        "meta_gord_g": round(gord_g, 1),
        "meta_carb_g": round(carb_g, 1),
        "meta_fibra_g": round(fibra_g, 1),
        "kcal_macros": round(kcal_macros, 1),
    }


# ---------------------------------------------------------------------------
# 2. SELEÇÃO DE REFEIÇÕES (resolve "Opção 1/2/3" do mesmo horário)
# ---------------------------------------------------------------------------

def nome_do_slot(nome_refeicao):
    """Extrai o horário-base do nome da refeição, agrupando suas variações.

    Os nomes reais variam muito: 'Pré Treino', 'Pré Treino - 1 hora antes
    (Toast de Banana)', 'Café da Manhã - Opção 2 (Crepioca)'. A parte antes do
    primeiro ' - ' (espaço-hífen-espaço) é o horário/refeição; o que vem depois
    é a variação. Assim todas as opções de um mesmo horário caem no mesmo slot.
    """
    nome = (nome_refeicao or "").strip()
    # Quebra no primeiro ' - ' ou ' – ' (hífen ou travessão entre espaços).
    base = re.split(r"\s+[-–]\s+", nome, maxsplit=1)[0]
    return base.strip()


def agrupar_em_slots(refeicoes):
    """Agrupa refeições por slot (horário). Retorna lista de (slot, [refeicoes])."""
    slots = {}
    ordem = []
    for r in refeicoes:
        slot = nome_do_slot(r.get("nome_refeicao", "Refeição"))
        if slot not in slots:
            slots[slot] = []
            ordem.append(slot)
        slots[slot].append(r)
    return [(s, slots[s]) for s in ordem]


# ---------------------------------------------------------------------------
# 3. FATORES DE ESCALA POR MACRONUTRIENTE
# ---------------------------------------------------------------------------

def _soma_macros_por_categoria(refeicoes_incluidas):
    """Soma o macro principal fornecido pelos alimentos de cada categoria."""
    total = {"Carboidrato": 0.0, "Proteína": 0.0, "Gordura": 0.0}
    for r in refeicoes_incluidas:
        for a in r.get("alimentos", []):
            cat = a.get("categoria", "Outro")
            if cat in total:
                macro_key = MACRO_PRINCIPAL[cat]
                total[cat] += (a.get("macros", {}) or {}).get(macro_key, 0) or 0
    return total


# Limites sãos para os fatores de escala — evita gramaturas absurdas quando o
# template fornece pouco de um macro (ex.: a gordura vem embutida em outros
# alimentos, não em itens da categoria "Gordura").
FATOR_MIN, FATOR_MAX = 0.25, 4.0


def calcular_fatores_macro(metas, refeicoes_incluidas):
    """Calcula os fatores de escala por categoria.

    ESTRATÉGIA (honesta para um template fixo):
      - Proteína e Carboidrato são ANCORADOS: escalamos seus alimentos para que
        o macro principal da categoria bata a meta.
      - Gordura é REPORTADA, não ancorada: o template tira gordura sobretudo de
        alimentos de proteína/carboidrato, então escalar os poucos itens
        "Gordura" para a meta explodiria a gramatura. Mantemos a gordura num
        fator neutro (acompanha o carboidrato) e mostramos o valor atingido para
        a nutricionista ajustar (ex.: azeite, oleaginosas, % de gordura).

    Todos os fatores são limitados a [FATOR_MIN, FATOR_MAX]. Retorna também a
    lista de avisos quando algum limite é atingido.
    """
    fornecido = _soma_macros_por_categoria(refeicoes_incluidas)
    avisos = []

    def _fator(meta_g, fornecido_g, nome):
        if fornecido_g <= 0:
            return 1.0
        bruto = meta_g / fornecido_g
        limitado = max(FATOR_MIN, min(FATOR_MAX, bruto))
        if abs(limitado - bruto) > 1e-6:
            avisos.append(
                f"Escala de {nome} limitada a {limitado:.2f}× "
                f"(ideal seria {bruto:.2f}×) — o template fornece pouco desse macro."
            )
        return limitado

    fator_carb = _fator(metas["meta_carb_g"], fornecido["Carboidrato"], "carboidrato")
    fator_prot = _fator(metas["meta_prot_g"], fornecido["Proteína"], "proteína")

    fatores = {
        "Carboidrato": fator_carb,
        "Proteína": fator_prot,
        "Gordura": fator_carb,  # neutro: acompanha o carboidrato (não ancora gordura)
        "Outro": 1.0,           # itens livres (café, temperos, vegetais) não escalam
    }
    return fatores, avisos


def escalar_alimento(alimento, fatores):
    """Escala um alimento pelo fator do macro da sua categoria."""
    cat = alimento.get("categoria", "Outro")
    fator = fatores.get(cat, 1.0)
    qtd_orig = alimento.get("quantidade_g", 0) or 0
    macros_orig = alimento.get("macros", {}) or {}

    novo = com_referencia_nutricional(alimento)
    novo["quantidade_original_g"] = qtd_orig
    novo["quantidade_g"] = round(qtd_orig * fator, 1)
    novo["calorias"] = round((alimento.get("calorias", 0) or 0) * fator, 1)
    novo["macros"] = {
        "carboidratos_g": round(macros_orig.get("carboidratos_g", 0) * fator, 1),
        "proteinas_g": round(macros_orig.get("proteinas_g", 0) * fator, 1),
        "gorduras_g": round(macros_orig.get("gorduras_g", 0) * fator, 1),
    }
    novo["substituido"] = False
    return novo


# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# 3.1 AJUSTE CONJUNTO COM LIMITES RÍGIDOS
# ---------------------------------------------------------------------------

CHAVES_NUTRICIONAIS = ("kcal", "carboidratos_g", "proteinas_g", "gorduras_g")
META_POR_CHAVE = {
    "kcal": "meta_kcal",
    "carboidratos_g": "meta_carb_g",
    "proteinas_g": "meta_prot_g",
    "gorduras_g": "meta_gord_g",
}
PESO_OTIMIZACAO = {
    "kcal": 1.5,
    "carboidratos_g": 1.0,
    "proteinas_g": 1.25,
    "gorduras_g": 1.0,
}
PRECISAO_PROFISSIONAL_G = 0.1


def nutrientes_alimento(alimento):
    """Vetor nutricional padronizado de um alimento."""
    macros = alimento.get("macros", {}) or {}
    return {
        "kcal": float(alimento.get("calorias", 0) or 0),
        "carboidratos_g": float(macros.get("carboidratos_g", 0) or 0),
        "proteinas_g": float(macros.get("proteinas_g", 0) or 0),
        "gorduras_g": float(macros.get("gorduras_g", 0) or 0),
    }


def com_referencia_nutricional(alimento, referencia=None):
    """Preserva uma base por grama para permitir reativar porções em 0 g."""
    novo = dict(alimento)
    existente = novo.get("referencia_nutricional") or {}
    if float(existente.get("quantidade_g", 0) or 0) > 0:
        novo["referencia_nutricional"] = {
            "quantidade_g": float(existente["quantidade_g"]),
            "calorias": float(existente.get("calorias", 0) or 0),
            "macros": {
                chave: float((existente.get("macros") or {}).get(chave, 0) or 0)
                for chave in CHAVES_NUTRICIONAIS if chave != "kcal"
            },
        }
        return novo

    base = referencia or alimento
    quantidade = float(base.get("quantidade_g", 0) or 0)
    valores = nutrientes_alimento(base)
    if quantidade <= 0 or not any(valor > 0 for valor in valores.values()):
        return novo
    novo["referencia_nutricional"] = {
        "quantidade_g": quantidade,
        "calorias": valores["kcal"],
        "macros": {
            chave: valores[chave]
            for chave in CHAVES_NUTRICIONAIS if chave != "kcal"
        },
    }
    return novo


def densidades_alimento(alimento):
    """Retorna kcal/macros por grama, inclusive quando a porção atual é zero."""
    referencia = alimento.get("referencia_nutricional") or {}
    quantidade = float(referencia.get("quantidade_g", 0) or 0)
    if quantidade > 0:
        macros = referencia.get("macros") or {}
        valores = {
            "kcal": float(referencia.get("calorias", 0) or 0),
            "carboidratos_g": float(macros.get("carboidratos_g", 0) or 0),
            "proteinas_g": float(macros.get("proteinas_g", 0) or 0),
            "gorduras_g": float(macros.get("gorduras_g", 0) or 0),
        }
        return {chave: valores[chave] / quantidade for chave in CHAVES_NUTRICIONAIS}

    quantidade = float(alimento.get("quantidade_g", 0) or 0)
    if quantidade <= 0:
        return {chave: 0.0 for chave in CHAVES_NUTRICIONAIS}
    valores = nutrientes_alimento(alimento)
    return {chave: valores[chave] / quantidade for chave in CHAVES_NUTRICIONAIS}


def somar_alimentos(alimentos, casas=3):
    totais = {chave: 0.0 for chave in CHAVES_NUTRICIONAIS}
    for alimento in alimentos:
        valores = nutrientes_alimento(alimento)
        for chave in CHAVES_NUTRICIONAIS:
            totais[chave] += valores[chave]
    return {chave: round(valor, casas) for chave, valor in totais.items()}


def totais_da_opcao(opcao, casas=3):
    return somar_alimentos(opcao.get("alimentos", []), casas=casas)


def somar_totais(slots, casas=3):
    """Soma somente a opção marcada como principal em cada horário."""
    totais = {chave: 0.0 for chave in CHAVES_NUTRICIONAIS}
    for grupo in slots:
        for opcao in grupo.get("opcoes", []):
            if not opcao.get("conta_no_total"):
                continue
            parcial = totais_da_opcao(opcao, casas=6)
            for chave in CHAVES_NUTRICIONAIS:
                totais[chave] += parcial[chave]
    return {chave: round(valor, casas) for chave, valor in totais.items()}


def limites_das_metas(metas):
    return {
        chave: max(float(metas.get(meta_chave, 0) or 0), 0.0)
        for chave, meta_chave in META_POR_CHAVE.items()
    }


def reescalar_alimento(alimento, gramas, casas_nutrientes=3):
    """Recalcula kcal e macros proporcionalmente à gramatura informada."""
    if gramas is None:
        return dict(alimento)
    gramas = max(float(gramas), 0.0)
    novo = com_referencia_nutricional(alimento)
    densidades = densidades_alimento(novo)
    novo["quantidade_g"] = round(gramas, 1)
    novo["calorias"] = round(densidades["kcal"] * gramas, casas_nutrientes)
    novo["macros"] = {
        chave: round(densidades[chave] * gramas, casas_nutrientes)
        for chave in CHAVES_NUTRICIONAIS
        if chave != "kcal"
    }
    novo["ajustado"] = True
    return novo


def quantidade_paciente(alimento):
    """Gramatura inteira para entrega, sempre para baixo para preservar os tetos."""
    gramas = max(float(alimento.get("quantidade_g", 0) or 0), 0.0)
    return int(math.floor(gramas + 1e-9))


PASSO_PORCAO_PACIENTE = 5


def arredondar_multiplo_proximo(valor, passo=PASSO_PORCAO_PACIENTE):
    """Arredonda para o múltiplo mais próximo; empates sobem."""
    valor = max(float(valor or 0), 0.0)
    if passo <= 0:
        return int(math.floor(valor + 0.5))
    unidades = math.floor((valor / passo) + 0.5 + 1e-9)
    return int(unidades * passo)


def arredondar_multiplo_para_baixo(valor, passo=PASSO_PORCAO_PACIENTE):
    """Arredonda para baixo até um múltiplo do passo."""
    valor = max(float(valor or 0), 0.0)
    if passo <= 0:
        return int(math.floor(valor + 1e-9))
    unidades = math.floor((valor / passo) + 1e-9)
    return int(unidades * passo)


def arredondar_alimentos_paciente(alimentos, limites=None,
                                  passo=PASSO_PORCAO_PACIENTE):
    """Cria porções práticas em múltiplos de 5 sem exceder os limites.

    Primeiro usa o múltiplo mais próximo. Se a soma arredondada ultrapassar
    algum limite da refeição, reduz porções em passos de 5 g até que kcal e os
    três macronutrientes voltem a ficar dentro dos tetos.
    """
    originais = [dict(alimento) for alimento in alimentos]
    quantidades_originais = [
        max(float(alimento.get("quantidade_g", 0) or 0), 0.0)
        for alimento in originais
    ]
    quantidades = [
        arredondar_multiplo_proximo(quantidade, passo)
        if quantidade > 0 else 0
        for quantidade in quantidades_originais
    ]
    if limites is None:
        limites = somar_alimentos(originais, casas=6)
    limites = {
        chave: max(float(limites.get(chave, 0) or 0), 0.0)
        for chave in CHAVES_NUTRICIONAIS
    }

    def materializar():
        resultado = []
        for alimento, quantidade in zip(originais, quantidades):
            novo = reescalar_alimento(alimento, quantidade)
            if float(alimento.get("quantidade_g", 0) or 0) <= 0:
                novo["quantidade_g"] = 0.0
            novo["arredondado_paciente"] = True
            resultado.append(novo)
        return resultado

    max_iteracoes = sum(
        int(quantidade / max(passo, 1)) + 1
        for quantidade in quantidades
    )
    atuais = materializar()
    for _ in range(max_iteracoes):
        totais = somar_alimentos(atuais, casas=6)
        excessos = {
            chave: max(totais[chave] - limites[chave], 0.0)
            for chave in CHAVES_NUTRICIONAIS
        }
        if not any(excesso > 1e-6 for excesso in excessos.values()):
            return atuais

        melhor = None
        for indice, quantidade in enumerate(quantidades):
            if quantidade < passo or quantidades_originais[indice] <= 0:
                continue
            reduzido = reescalar_alimento(
                originais[indice], quantidade - passo
            )
            atual_nutrientes = nutrientes_alimento(atuais[indice])
            novo_nutrientes = nutrientes_alimento(reduzido)
            reducoes = {
                chave: max(
                    atual_nutrientes[chave] - novo_nutrientes[chave], 0.0
                )
                for chave in CHAVES_NUTRICIONAIS
            }
            score = sum(
                (
                    excessos[chave] / max(limites[chave], 1.0)
                ) * reducoes[chave]
                for chave in CHAVES_NUTRICIONAIS
                if excessos[chave] > 1e-6
            )
            if score <= 0:
                continue
            dist_atual = abs(
                quantidade - quantidades_originais[indice]
            )
            dist_nova = abs(
                (quantidade - passo) - quantidades_originais[indice]
            )
            criterio = (score, dist_atual - dist_nova, quantidade)
            if melhor is None or criterio > melhor[0]:
                melhor = (criterio, indice)

        if melhor is None:
            break
        quantidades[melhor[1]] -= passo
        atuais = materializar()

    # Salvaguarda extrema: reduzir qualquer item nutritivo até ficar seguro.
    while any(
        somar_alimentos(atuais, casas=6)[chave] > limites[chave] + 1e-6
        for chave in CHAVES_NUTRICIONAIS
    ):
        candidatos = [
            indice for indice, quantidade in enumerate(quantidades)
            if quantidade >= passo
            and any(
                valor > 0
                for valor in nutrientes_alimento(atuais[indice]).values()
            )
        ]
        if not candidatos:
            break
        indice = max(
            candidatos,
            key=lambda i: sum(nutrientes_alimento(atuais[i]).values()),
        )
        quantidades[indice] -= passo
        atuais = materializar()
    return atuais


def excedentes_metas(totais, metas, tolerancia=1e-6):
    """Lista os nutrientes que ultrapassaram seus limites."""
    limites = limites_das_metas(metas)
    return {
        chave: {
            "atingido": float(totais.get(chave, 0) or 0),
            "limite": limite,
            "excesso": round(float(totais.get(chave, 0) or 0) - limite, 3),
        }
        for chave, limite in limites.items()
        if float(totais.get(chave, 0) or 0) > limite + tolerancia
    }


def _densidades(alimento):
    return densidades_alimento(alimento)


def _arredondar_para_baixo(valor, passo=PRECISAO_PROFISSIONAL_G):
    if passo <= 0:
        return max(float(valor), 0.0)
    unidades = math.floor((max(float(valor), 0.0) / passo) + 1e-9)
    return round(unidades * passo, 10)


def otimizar_quantidades(alimentos, limites, max_iteracoes=300,
                         regularizacao=0.001):
    """Aproxima quatro metas sem permitir ultrapassagens.

    É uma descida coordenada para mínimos quadráticos normalizados com:
      - quantidades não negativas;
      - kcal, carboidrato, proteína e gordura como limites superiores rígidos;
      - regularização leve para preservar a estrutura do cardápio-base.

    A saída profissional usa décimos de grama arredondados para baixo.
    """
    saida = [dict(alimento) for alimento in alimentos]
    limites = {
        chave: max(float(limites.get(chave, 0) or 0), 0.0)
        for chave in CHAVES_NUTRICIONAIS
    }
    indices = [
        i for i, alimento in enumerate(saida)
        if float(alimento.get("quantidade_g", 0) or 0) > 0
        and any(valor > 0 for valor in _densidades(alimento).values())
    ]
    if not indices:
        return saida, {
            "totais": somar_alimentos(saida),
            "iteracoes": 0,
            "convergiu": True,
        }

    bases = [float(saida[i].get("quantidade_g", 0) or 0) for i in indices]
    densidades = [_densidades(saida[i]) for i in indices]
    quantidades = list(bases)

    fixos = [
        alimento for i, alimento in enumerate(saida)
        if i not in set(indices)
    ]
    totais_fixos = somar_alimentos(fixos, casas=9)

    def _totais(qtds):
        resultado = dict(totais_fixos)
        for qtd, densidade in zip(qtds, densidades):
            for chave in CHAVES_NUTRICIONAIS:
                resultado[chave] += qtd * densidade[chave]
        return resultado

    # Começa numa região factível, reduzindo todas as porções se necessário.
    totais = _totais(quantidades)
    fatores = [
        limites[chave] / totais[chave]
        for chave in CHAVES_NUTRICIONAIS
        if totais[chave] > limites[chave] and totais[chave] > 0
    ]
    if fatores:
        fator = max(min(fatores), 0.0)
        quantidades = [qtd * fator for qtd in quantidades]
        totais = _totais(quantidades)

    convergiu = False
    iteracoes = 0
    for iteracoes in range(1, max_iteracoes + 1):
        maior_delta = 0.0
        for pos, (base, densidade) in enumerate(zip(bases, densidades)):
            antiga = quantidades[pos]
            sem_item = {
                chave: totais[chave] - (antiga * densidade[chave])
                for chave in CHAVES_NUTRICIONAIS
            }

            maximo = float("inf")
            for chave in CHAVES_NUTRICIONAIS:
                por_g = densidade[chave]
                if por_g > 0:
                    maximo = min(
                        maximo,
                        max((limites[chave] - sem_item[chave]) / por_g, 0.0),
                    )
            if not math.isfinite(maximo):
                maximo = max(base * 4, 2000.0)

            numerador = 0.0
            denominador = 0.0
            for chave in CHAVES_NUTRICIONAIS:
                alvo = limites[chave]
                escala = max(alvo, 1.0)
                peso = PESO_OTIMIZACAO[chave]
                por_g = densidade[chave]
                numerador += peso * por_g * (alvo - sem_item[chave]) / (escala ** 2)
                denominador += peso * (por_g ** 2) / (escala ** 2)

            escala_base = max(base, 1.0)
            numerador += regularizacao * base / (escala_base ** 2)
            denominador += regularizacao / (escala_base ** 2)
            candidata = numerador / denominador if denominador > 0 else antiga
            nova = min(max(candidata, 0.0), maximo)
            quantidades[pos] = nova
            for chave in CHAVES_NUTRICIONAIS:
                totais[chave] = sem_item[chave] + (nova * densidade[chave])
            maior_delta = max(maior_delta, abs(nova - antiga))

        if maior_delta < 0.0005:
            convergiu = True
            break


    # Refinamento projetado: permite trocas simultâneas de composição quando
    # um nutriente já está no teto (situação em que um passo por vez estagna).
    contribuicoes = {
        chave: [
            base * densidade[chave]
            for base, densidade in zip(bases, densidades)
        ]
        for chave in CHAVES_NUTRICIONAIS
    }
    proporcoes = [
        quantidade / base if base > 0 else 0.0
        for quantidade, base in zip(quantidades, bases)
    ]
    regularizacao_refino = min(regularizacao, 0.00002)
    lipschitz = 2 * regularizacao_refino
    for chave in CHAVES_NUTRICIONAIS:
        escala = max(limites[chave], 1.0)
        norma = sum(valor ** 2 for valor in contribuicoes[chave])
        lipschitz += (
            2 * PESO_OTIMIZACAO[chave] * norma / (escala ** 2)
        )
    passo = 0.9 / max(lipschitz, 1e-9)
    max_refino = max(600, min(2000, max_iteracoes * 4))
    for _ in range(max_refino):
        totais_refino = {
            chave: totais_fixos[chave] + sum(
                valor * proporcao
                for valor, proporcao in zip(contribuicoes[chave], proporcoes)
            )
            for chave in CHAVES_NUTRICIONAIS
        }
        gradiente = []
        for pos in range(len(proporcoes)):
            valor = 0.0
            for chave in CHAVES_NUTRICIONAIS:
                escala = max(limites[chave], 1.0)
                valor += (
                    2 * PESO_OTIMIZACAO[chave]
                    * contribuicoes[chave][pos]
                    * (totais_refino[chave] - limites[chave])
                    / (escala ** 2)
                )
            valor += 2 * regularizacao_refino * (proporcoes[pos] - 1.0)
            gradiente.append(valor)

        novas = [
            max(proporcao - (passo * gradiente[pos]), 0.0)
            for pos, proporcao in enumerate(proporcoes)
        ]
        for _projecao in range(5):
            for chave in CHAVES_NUTRICIONAIS:
                vetor = contribuicoes[chave]
                total = totais_fixos[chave] + sum(
                    valor * proporcao for valor, proporcao in zip(vetor, novas)
                )
                if total <= limites[chave] + 1e-9:
                    continue
                norma = sum(valor ** 2 for valor in vetor)
                if norma <= 0:
                    continue
                deslocamento = (total - limites[chave]) / norma
                novas = [
                    max(proporcao - (deslocamento * vetor[pos]), 0.0)
                    for pos, proporcao in enumerate(novas)
                ]

        delta = max(
            abs(nova - antiga)
            for nova, antiga in zip(novas, proporcoes)
        )
        proporcoes = novas
        if delta < 1e-8:
            convergiu = True
            break

    quantidades = [
        base * proporcao for base, proporcao in zip(bases, proporcoes)
    ]
    quantidades = [_arredondar_para_baixo(qtd) for qtd in quantidades]
    for indice, qtd in zip(indices, quantidades):
        saida[indice] = reescalar_alimento(saida[indice], qtd)

    totais_saida = somar_alimentos(saida, casas=6)
    excedentes = {
        chave: totais_saida[chave] - limites[chave]
        for chave in CHAVES_NUTRICIONAIS
        if totais_saida[chave] > limites[chave] + 1e-6
    }
    if excedentes:
        fatores = [
            limites[chave] / totais_saida[chave]
            for chave in excedentes
            if totais_saida[chave] > 0
        ]
        fator = max(min(fatores) - 1e-9, 0.0)
        for indice in indices:
            qtd = _arredondar_para_baixo(
                float(saida[indice].get("quantidade_g", 0) or 0) * fator
            )
            saida[indice] = reescalar_alimento(saida[indice], qtd)
        totais_saida = somar_alimentos(saida, casas=6)

    return saida, {
        "totais": {chave: round(valor, 3) for chave, valor in totais_saida.items()},
        "iteracoes": iteracoes,
        "convergiu": convergiu,
    }


def maximo_gramas_por_limites(alimento, limites, totais_fixos=None,
                              maximo_padrao=2000.0):
    """Maior porção possível se os demais itens ajustáveis puderem ceder espaço."""
    densidades = densidades_alimento(alimento)
    fixos = totais_fixos or {}
    maximos = [float(maximo_padrao)]
    for chave in CHAVES_NUTRICIONAIS:
        por_grama = densidades[chave]
        if por_grama <= 0 or chave not in limites:
            continue
        disponivel = (
            float(limites.get(chave, 0) or 0)
            - float(fixos.get(chave, 0) or 0)
        )
        maximos.append(max(disponivel / por_grama, 0.0))
    return _arredondar_para_baixo(min(maximos))


def readequar_opcao_com_ancora(alimentos, limites, indice_ancora, gramas,
                               totais_fixos=None):
    """Fixa uma porção e reotimiza os demais itens da mesma opção.

    `totais_fixos` representa adições que não pertencem à lista ajustável. O
    alimento editado é preservado na quantidade solicitada sempre que ele,
    sozinho, cabe no envelope nutricional restante.
    """
    if not 0 <= indice_ancora < len(alimentos):
        raise IndexError("Índice do alimento âncora fora da opção.")

    saida = [dict(alimento) for alimento in alimentos]
    limites = {
        chave: max(float(limites.get(chave, 0) or 0), 0.0)
        for chave in CHAVES_NUTRICIONAIS
    }
    fixos = {
        chave: max(float((totais_fixos or {}).get(chave, 0) or 0), 0.0)
        for chave in CHAVES_NUTRICIONAIS
    }
    solicitado = max(float(gramas or 0), 0.0)
    maximo = maximo_gramas_por_limites(
        saida[indice_ancora], limites, totais_fixos=fixos
    )
    aplicado = _arredondar_para_baixo(min(solicitado, maximo))
    saida[indice_ancora] = reescalar_alimento(
        saida[indice_ancora], aplicado
    )

    densidades_ancora = densidades_alimento(saida[indice_ancora])
    if any(valor > 0 for valor in densidades_ancora.values()):
        nutrientes_ancora = nutrientes_alimento(saida[indice_ancora])
        limites_restantes = {
            chave: max(
                limites[chave] - fixos[chave] - nutrientes_ancora[chave],
                0.0,
            )
            for chave in CHAVES_NUTRICIONAIS
        }
        indices_restantes = [
            indice for indice in range(len(saida)) if indice != indice_ancora
        ]
        restantes = [saida[indice] for indice in indices_restantes]
        otimizados, _ = otimizar_quantidades(restantes, limites_restantes)
        for indice, alimento in zip(indices_restantes, otimizados):
            saida[indice] = alimento

    totais_saida = somar_alimentos(saida, casas=6)
    totais_com_fixos = {
        chave: round(totais_saida[chave] + fixos[chave], 6)
        for chave in CHAVES_NUTRICIONAIS
    }
    limitado = aplicado + 1e-9 < solicitado
    return saida, {
        "quantidade_solicitada_g": round(solicitado, 1),
        "quantidade_aplicada_g": round(aplicado, 1),
        "maximo_g": round(maximo, 1),
        "limitado": limitado,
        "totais": totais_com_fixos,
    }

# 4. SUBSTITUIÇÃO POR AVERSÃO / ALERGIA (lógica "Isabela/Yuri")
# ---------------------------------------------------------------------------

def deve_excluir(nome_alimento, termos_excluidos_norm):
    """True se algum termo de aversão/alergia aparece no nome do alimento."""
    nome_norm = normalizar_texto(nome_alimento)
    return any(termo and termo in nome_norm for termo in termos_excluidos_norm)


def _tem_termo(nome_norm, termos):
    return any(termo in nome_norm for termo in termos)


def _porcao_ideal(categoria):
    return PORCAO_IDEAL_G.get(categoria, (20, 350))


def _porcao_maxima(categoria):
    return PORCAO_MAXIMA_G.get(categoria, 600)


def _grupo_preferencial(nome):
    nome_norm = normalizar_texto(nome)
    if _tem_termo(nome_norm, FRUTAS):
        return "fruta"
    if _tem_termo(nome_norm, AMIDOS):
        return "amido"
    if _tem_termo(nome_norm, PROTEINAS):
        return "proteina"
    if _tem_termo(nome_norm, GORDURAS):
        return "gordura"
    return None


def _candidato_no_grupo(alimento, grupo):
    nome_norm = normalizar_texto(alimento.get("nome_alimento", ""))
    classe_norm = normalizar_texto(alimento.get("classe", ""))
    if grupo == "fruta":
        return classe_norm == "frutas e derivados" and not _tem_termo(nome_norm, TERMOS_BEBIDA)
    if grupo == "amido":
        return classe_norm in {
            "cereais e derivados",
            "leguminosas e derivados",
            "vegetais e derivados",
        }
    if grupo == "proteina":
        return classe_norm in {
            "carnes e derivados",
            "pescados e frutos do mar",
            "pescados e frutos do mar",
            "ovos e derivados",
            "leite e derivados",
        }
    if grupo == "gordura":
        return classe_norm in {"gorduras e oleos", "sementes e oleaginosas"}
    return True


def _chave_dedupe_substituto(nome, grupo):
    nome_norm = normalizar_texto(nome)
    if grupo == "fruta":
        for fruta in FRUTAS_COMUNS:
            if fruta in nome_norm:
                return f"fruta:{fruta}"
    return nome_norm


def _cautelas_substituto(alimento):
    nome_norm = normalizar_texto(alimento.get("nome_alimento", ""))
    classe_norm = normalizar_texto(alimento.get("classe", ""))
    cautelas = []
    if _tem_termo(nome_norm, TERMOS_PRATO_COMPOSTO):
        cautelas.append("prato composto")
    if _tem_termo(nome_norm, TERMOS_ULTRAPROCESSADO):
        cautelas.append("ultraprocessado")
    if classe_norm in CLASSES_CAUTELA:
        cautelas.append("classe de açúcar/doce")
    return cautelas


def _pontuar_substituto(alimento_origem, sub, categoria, macro_key, macro_alvo):
    chave_tbca = MACRO_PARA_CHAVE_TBCA[macro_key]
    macro_por_100g = sub.get(chave_tbca, 0) or 0
    if macro_por_100g <= 0:
        return None

    gramas = calcular_nova_gramatura(macro_alvo, macro_por_100g)
    if gramas <= 0:
        return None

    f = gramas / 100.0
    macros = {
        "carboidratos_g": round((sub.get("carboidrato", 0) or 0) * f, 1),
        "proteinas_g": round((sub.get("proteina", 0) or 0) * f, 1),
        "gorduras_g": round((sub.get("lipidios", 0) or 0) * f, 1),
    }
    calorias = round((sub.get("energia_kcal", 0) or 0) * f, 1)

    score = 100.0
    motivos = [
        f"mesma categoria: {categoria}",
        f"fornece {macro_alvo:.1f} g de {ROTULO_MACRO[macro_key]} com {gramas:.0f} g",
    ]
    alertas = []

    min_g, ideal_max_g = _porcao_ideal(categoria)
    max_g = _porcao_maxima(categoria)
    if gramas < min_g:
        penalidade = min(25.0, ((min_g - gramas) / min_g) * 25.0)
        score -= penalidade
        alertas.append(f"porção baixa ({gramas:.0f} g)")
    elif gramas > ideal_max_g:
        penalidade = min(35.0, ((gramas - ideal_max_g) / ideal_max_g) * 35.0)
        score -= penalidade
        alertas.append(f"porção alta ({gramas:.0f} g)")
    else:
        motivos.append("porção dentro da faixa de revisão")

    if gramas > max_g:
        score -= 50.0
        alertas.append(f"acima do limite prático ({max_g:.0f} g)")

    kcal_origem = alimento_origem.get("calorias", 0) or 0
    if kcal_origem > 0:
        diff_pct = abs(calorias - kcal_origem) / kcal_origem
        score -= min(30.0, diff_pct * 30.0)
        if diff_pct <= 0.20:
            motivos.append("calorias próximas do alimento original")
        else:
            alertas.append(f"calorias {diff_pct * 100:.0f}% diferentes do original")

    nome_norm = normalizar_texto(sub.get("nome_alimento", ""))
    origem_norm = normalizar_texto(alimento_origem.get("nome_principal", ""))
    grupo_origem = _grupo_preferencial(alimento_origem.get("nome_principal", ""))
    tokens_nome = [t for t in re.sub(r"[^a-z0-9 ]", " ", nome_norm).split() if len(t) > 1]
    if len(tokens_nome) > 5:
        score -= min(12.0, (len(tokens_nome) - 5) * 2.0)

    if grupo_origem:
        if _candidato_no_grupo(sub, grupo_origem):
            score += 10.0
            motivos.append(f"mantém grupo alimentar: {grupo_origem}")
        else:
            score -= 35.0
            alertas.append(f"grupo alimentar diferente de {grupo_origem}")

    qtd_origem = alimento_origem.get("quantidade_g", 0) or 0
    if qtd_origem > 0:
        diff_qtd_pct = abs(gramas - qtd_origem) / qtd_origem
        score -= min(20.0, diff_qtd_pct * 15.0)
        if diff_qtd_pct <= 0.35:
            motivos.append("porção próxima da original")

    if grupo_origem == "fruta" and _tem_termo(nome_norm, TERMOS_FRUTA_SECA) and not _tem_termo(
        origem_norm, TERMOS_FRUTA_SECA
    ):
        score -= 25.0
        alertas.append("fruta seca/concentrada")

    if grupo_origem == "fruta":
        if _tem_termo(nome_norm, FRUTAS_COMUNS):
            score += 15.0
            motivos.append("fruta comum na rotina alimentar")
        else:
            score -= 15.0
            alertas.append("fruta menos comum")
        if "in natura" in nome_norm or "cru" in nome_norm:
            score += 8.0
            motivos.append("fruta in natura")
        if _tem_termo(nome_norm, TERMOS_PARTE_NAO_USUAL):
            score -= 45.0
            alertas.append("parte não usual do alimento")
        if _tem_termo(nome_norm, TERMOS_PREPARO_FRUTA_PENALIZADO) and not _tem_termo(
            origem_norm, TERMOS_PREPARO_FRUTA_PENALIZADO
        ):
            score -= 30.0
            alertas.append("preparo de fruta pouco adequado como substituição padrão")

    if _tem_termo(nome_norm, TERMOS_INGREDIENTE_BRUTO) and not _tem_termo(
        origem_norm, TERMOS_INGREDIENTE_BRUTO
    ):
        score -= 35.0
        alertas.append("ingrediente bruto/pouco prático")

    if _tem_termo(nome_norm, TERMOS_ACUCAR_ADICIONADO) and not _tem_termo(
        origem_norm, TERMOS_ACUCAR_ADICIONADO
    ):
        score -= 35.0
        alertas.append("açúcar/adocante no substituto")

    if _tem_termo(nome_norm, TERMOS_BEBIDA) and not _tem_termo(origem_norm, TERMOS_BEBIDA):
        score -= 30.0
        alertas.append("bebida no lugar de alimento sólido")

    cautelas = _cautelas_substituto(sub)
    for cautela in cautelas:
        if cautela == "classe de açúcar/doce":
            score -= 35.0
        elif cautela == "ultraprocessado":
            score -= 25.0
        else:
            score -= 20.0
        alertas.append(cautela)

    return {
        "alimento": sub,
        "nome": sub.get("nome_alimento", ""),
        "quantidade_g": round(gramas, 1),
        "calorias": calorias,
        "macros": macros,
        "score": round(max(score, 0.0), 1),
        "motivos": motivos,
        "alertas": alertas,
    }


def buscar_substitutos_ranqueados(alimento_escalado, banco, termos_excluidos_norm, limite=5):
    """Lista substitutos determinísticos, ranqueados e auditáveis.

    A gramatura de cada candidato é calculada para bater o macro principal do
    alimento excluído. O score favorece porção viável, calorias próximas e nomes
    simples; penaliza pratos compostos, ultraprocessados e doces.
    """
    categoria = alimento_escalado.get("categoria", "Outro")
    macro_key = MACRO_PRINCIPAL.get(categoria)
    if not macro_key:
        return []

    macro_alvo = (alimento_escalado.get("macros", {}) or {}).get(macro_key, 0) or 0
    if macro_alvo <= 0:
        return []

    chave_tbca = MACRO_PARA_CHAVE_TBCA[macro_key]
    pontuados = []
    for candidato in banco:
        if candidato.get("categoria") != categoria:
            continue
        if candidato.get("energia_kcal", 0) <= 0 or candidato.get(chave_tbca, 0) <= 0:
            continue
        if deve_excluir(candidato.get("nome_alimento", ""), termos_excluidos_norm):
            continue
        item = _pontuar_substituto(alimento_escalado, candidato, categoria, macro_key, macro_alvo)
        if item:
            pontuados.append(item)

    qtd_origem = alimento_escalado.get("quantidade_g", 0) or 0
    pontuados.sort(
        key=lambda i: (
            -i["score"],
            abs(i["quantidade_g"] - qtd_origem) if qtd_origem > 0 else i["quantidade_g"],
            normalizar_texto(i["nome"]),
        )
    )

    grupo_origem = _grupo_preferencial(alimento_escalado.get("nome_principal", ""))
    unicos = []
    vistos = set()
    for item in pontuados:
        chave = _chave_dedupe_substituto(item["nome"], grupo_origem)
        if chave in vistos:
            continue
        vistos.add(chave)
        unicos.append(item)
        if len(unicos) >= limite:
            break
    return unicos


def buscar_substituto(categoria, banco, termos_excluidos_norm):
    """Retorna um substituto determinístico simples para compatibilidade."""
    macro_key = MACRO_PRINCIPAL.get(categoria, "carboidratos_g")
    chave_tbca = MACRO_PARA_CHAVE_TBCA[macro_key]
    candidatos = [
        a for a in banco
        if a["categoria"] == categoria
        and a["energia_kcal"] > 0
        and a[chave_tbca] > 0
        and not deve_excluir(a["nome_alimento"], termos_excluidos_norm)
    ]
    candidatos.sort(key=lambda a: normalizar_texto(a["nome_alimento"]))
    return candidatos[0] if candidatos else None


def calcular_nova_gramatura(macro_alvo_g, macro_substituto_por_100g):
    """Regra de três: gramas do substituto para fornecer 'macro_alvo_g' do macro.

    Ex.: o alimento removido fornece 18 g de carbo; o substituto tem 23 g de
    carbo por 100 g -> 100 * 18 / 23 ≈ 78 g do substituto.
    """
    if macro_substituto_por_100g <= 0:
        return 0.0
    return round(100 * macro_alvo_g / macro_substituto_por_100g, 1)


def aplicar_swap(alimento_escalado, banco, termos_excluidos_norm):
    """Substitui alimento excluído com candidato ranqueado e marcado para revisão."""
    if not deve_excluir(alimento_escalado.get("nome_principal", ""), termos_excluidos_norm):
        return alimento_escalado, False

    opcoes = buscar_substitutos_ranqueados(alimento_escalado, banco, termos_excluidos_norm)
    if not opcoes:
        final = dict(alimento_escalado)
        final.update(substituido=True, nome_substituto="(sem substituto na categoria)",
                     quantidade_g=0, substituicao_automatica=True, exige_revisao=True,
                     alertas_substituicao=["sem substituto adequado na categoria"])
        return final, True

    melhor = opcoes[0]

    final = dict(alimento_escalado)
    final.update(
        substituido=True,
        substituicao_automatica=True,
        exige_revisao=True,
        nome_original=alimento_escalado.get("nome_principal", ""),
        nome_substituto=melhor["nome"],
        nome_principal=melhor["nome"],
        quantidade_g=melhor["quantidade_g"],
        calorias=melhor["calorias"],
        macros=melhor["macros"],
        score_substituicao=melhor["score"],
        motivos_substituicao=melhor["motivos"],
        alertas_substituicao=melhor["alertas"],
        opcoes_substituicao_sugeridas=[
            {k: o[k] for k in ("nome", "quantidade_g", "calorias", "score", "motivos", "alertas")}
            for o in opcoes
        ],
    )
    return final, True


# ---------------------------------------------------------------------------
# 5. GERAÇÃO DO CARDÁPIO COMPLETO
# ---------------------------------------------------------------------------

def gerar_cardapio(template, banco, metas, termos_excluidos, opcao_por_slot=None):
    """Gera opções equivalentes sem exceder kcal ou macronutrientes.

    Primeiro é montado o esqueleto completo, incluindo substituições clínicas.
    Depois, todas as porções principais são otimizadas em conjunto. Cada opção
    alternativa é ajustada aos limites nutricionais da principal do seu horário;
    assim qualquer combinação de opções continua dentro dos limites diários.
    """
    termos_norm = [normalizar_texto(t) for t in termos_excluidos if t and t.strip()]
    grupos = agrupar_em_slots(template["refeicoes"])
    opcao_por_slot = opcao_por_slot or {}

    incluidas = []
    indices_principais = {}
    for slot, opcoes in grupos:
        indice = opcao_por_slot.get(slot, 0)
        indice = indice if 0 <= indice < len(opcoes) else 0
        indices_principais[slot] = indice
        incluidas.append(opcoes[indice])

    fatores, avisos = calcular_fatores_macro(metas, incluidas)
    slots_resultado = []
    for slot, opcoes in grupos:
        indice_principal = indices_principais[slot]
        opcoes_resultado = []
        for indice, refeicao in enumerate(opcoes):
            alimentos_finais = []
            for alimento in refeicao.get("alimentos", []):
                escalado = escalar_alimento(alimento, fatores)
                final, _ = aplicar_swap(escalado, banco, termos_norm)
                alimentos_finais.append(final)
            opcoes_resultado.append({
                "nome_refeicao": refeicao.get("nome_refeicao", "Refeição"),
                "horario": refeicao.get("horario"),
                "observacoes": refeicao.get("observacoes_da_refeicao"),
                "alimentos": alimentos_finais,
                "conta_no_total": indice == indice_principal,
            })
        slots_resultado.append({"slot": slot, "opcoes": opcoes_resultado})

    principais = []
    referencias = []
    for grupo in slots_resultado:
        principal = next(
            opcao for opcao in grupo["opcoes"] if opcao.get("conta_no_total")
        )
        referencias.append(principal)
        principais.extend(principal["alimentos"])

    otimizados, diagnostico = otimizar_quantidades(
        principais, limites_das_metas(metas)
    )
    cursor = 0
    for principal in referencias:
        quantidade = len(principal["alimentos"])
        principal["alimentos"] = otimizados[cursor:cursor + quantidade]
        principal["limites_nutricionais"] = totais_da_opcao(principal)
        cursor += quantidade

    # Alternativas ficam nutricionalmente limitadas pela principal do horário.
    for grupo, principal in zip(slots_resultado, referencias):
        limites_refeicao = totais_da_opcao(principal, casas=6)
        for opcao in grupo["opcoes"]:
            opcao["limites_nutricionais"] = dict(limites_refeicao)
            if opcao is principal:
                continue
            opcao["alimentos"], _ = otimizar_quantidades(
                opcao["alimentos"], limites_refeicao
            )

    totais = somar_totais(slots_resultado, casas=3)
    limites = limites_das_metas(metas)
    rotulos = {
        "kcal": "calorias",
        "carboidratos_g": "carboidrato",
        "proteinas_g": "proteína",
        "gorduras_g": "gordura",
    }
    abaixo = []
    for chave in CHAVES_NUTRICIONAIS:
        limite = limites[chave]
        atingido = totais[chave]
        tolerancia = max(0.5, limite * 0.01)
        if limite > 0 and atingido < limite - tolerancia:
            unidade = "kcal" if chave == "kcal" else "g"
            abaixo.append(
                f"{rotulos[chave]} {atingido:.1f}/{limite:.1f} {unidade}"
            )
    if abaixo:
        avisos.append(
            "O cardápio respeita todos os tetos, mas a combinação atual de "
            "alimentos não alcançou integralmente: " + "; ".join(abaixo) + "."
        )
    if not diagnostico["convergiu"]:
        avisos.append(
            "O ajuste atingiu o limite interno de iterações; revise as porções."
        )
    return slots_resultado, totais, fatores, avisos


# ---------------------------------------------------------------------------
# 6. VALIDAÇÃO AUTOMÁTICA DOS CÁLCULOS (roda dentro do app)
# ---------------------------------------------------------------------------

def parse_opcao_substituicao(texto):
    """Interpreta uma opção curada -> (nome, gramas).

    'Mamão - 200g' -> ('Mamão', 200) ; '15g Queijo Cottage' -> ('Queijo Cottage', 15)
    '185ml de Suco de uva Integral' -> ('Suco de uva Integral', 185).
    """
    if not texto:
        return None, None
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*(?:g|ml)\b", texto, re.IGNORECASE)
    gramas = numero_br_para_float(m.group(1)) if m else None
    nome = (texto[:m.start()] + texto[m.end():]) if m else texto
    nome = re.sub(r"^\s*(de|do|da)\s+", "", nome.strip(" -–:|"), flags=re.IGNORECASE)
    return (nome.strip(" -–:|") or None), gramas


def _fmt_quantidade(n):
    """Formata 0.5->'½', 1.5->'1½', 2->'2' para a medida caseira."""
    inteiro = int(n)
    frac = n - inteiro
    meia = "½" if abs(frac - 0.5) < 0.01 else ""
    if inteiro == 0:
        return meia or "0"
    return f"{inteiro}{meia}"


def _pluralizar_unidade(unidade, n):
    """Pluraliza a 1ª palavra da medida (regras do PT): 'colher de sopa' ->
    'colheres de sopa'; 'fatia' -> 'fatias'. Mantém o resto igual."""
    if n <= 1:
        return unidade
    partes = unidade.split()
    if not partes:
        return unidade
    p = partes[0]
    if p.endswith(("r", "z")):
        plural = p + "es"
    elif p.endswith("l"):
        plural = p[:-1] + "is"
    elif p.endswith("m"):
        plural = p[:-1] + "ns"
    elif p[-1:].lower() in "aeiouáéíóúâ":
        plural = p + "s"
    else:
        plural = p + "s"
    return " ".join([plural] + partes[1:])


def descrever_porcao(alimento, inteiro=False):
    """Texto amigável da porção: '60 g (≈ 2½ colheres de sopa)'.

    Usa a medida caseira do alimento (gramas_por_unidade) recalculada para a
    gramatura atual (já escalada). Sem medida conhecida, mostra só as gramas.
    """
    g = (quantidade_paciente(alimento) if inteiro
         else float(alimento.get("quantidade_g", 0) or 0))
    if inteiro:
        base = f"{int(g)} g"
    else:
        base = f"{g:.0f} g" if abs(g - round(g)) < 0.05 else f"{g:.1f} g"
    gpu = alimento.get("gramas_por_unidade")
    unidade = alimento.get("medida_unidade")
    if not gpu or not unidade or g <= 0:
        return base
    n = round((g / gpu) * 2) / 2  # arredonda para a meia-unidade mais próxima
    if n <= 0:
        return base
    return f"{base} (≈ {_fmt_quantidade(n)} {_pluralizar_unidade(unidade.lower(), n)})"


def _atwater(macros):
    """kcal teórica a partir dos macros (4 kcal/g carbo e prot; 9 kcal/g gord)."""
    macros = macros or {}
    return (4 * macros.get("carboidratos_g", 0)
            + 4 * macros.get("proteinas_g", 0)
            + 9 * macros.get("gorduras_g", 0))


def validar_resultado(slots, totais, metas, tol_pct=25, tol_abs=20):
    """Confere a coerência do cardápio gerado. Retorna um dicionário de checagens.

      - somas_ok: a soma dos alimentos bate com os totais informados.
      - incoerentes: alimentos cujas calorias não fecham com os macros (Atwater)
        — denuncia dado nutricional suspeito.
      - desvios: atingido vs meta por macro (e kcal), em %.
    """
    soma = {"kcal": 0.0, "carboidratos_g": 0.0, "proteinas_g": 0.0, "gorduras_g": 0.0}
    incoerentes = []
    n_alimentos = 0

    for s in slots:
        for op in s["opcoes"]:
            if not op["conta_no_total"]:
                continue
            for a in op["alimentos"]:
                kcal = a.get("calorias", 0) or 0
                soma["kcal"] += kcal
                for k in ("carboidratos_g", "proteinas_g", "gorduras_g"):
                    soma[k] += a.get("macros", {}).get(k, 0) or 0
                if kcal <= 0:
                    continue
                n_alimentos += 1
                atw = _atwater(a.get("macros", {}))
                desvio = abs(kcal - atw)
                pct = (desvio / kcal * 100) if kcal else 0
                if desvio > tol_abs and pct > tol_pct:
                    incoerentes.append({
                        "nome": a.get("nome_principal", ""),
                        "kcal": round(kcal), "atwater": round(atw), "pct": round(pct),
                    })

    somas_ok = all(abs(round(soma[k], 1) - totais.get(k, 0)) <= 1 for k in soma)

    pares = [("kcal", "meta_kcal"), ("carboidratos_g", "meta_carb_g"),
             ("proteinas_g", "meta_prot_g"), ("gorduras_g", "meta_gord_g")]
    desvios = {}
    for chave, meta_key in pares:
        atingido = totais.get(chave, 0)
        meta = metas.get(meta_key, 0)
        pct = ((atingido - meta) / meta * 100) if meta else 0
        desvios[chave] = {"atingido": atingido, "meta": meta, "pct": round(pct)}

    excedentes = excedentes_metas(soma, metas)
    opcoes_excedentes = []
    for grupo in slots:
        for opcao in grupo.get("opcoes", []):
            limites_opcao = opcao.get("limites_nutricionais")
            if not limites_opcao:
                continue
            total_opcao = totais_da_opcao(opcao)
            excesso = {
                chave: round(total_opcao[chave] - limites_opcao[chave], 3)
                for chave in CHAVES_NUTRICIONAIS
                if total_opcao[chave] > float(limites_opcao.get(chave, 0)) + 1e-6
            }
            if excesso:
                opcoes_excedentes.append({
                    "slot": grupo.get("slot", ""),
                    "opcao": opcao.get("nome_refeicao", ""),
                    "excedentes": excesso,
                    "detalhes": {
                        chave: {
                            "atingido": round(total_opcao[chave], 3),
                            "limite": round(float(limites_opcao[chave]), 3),
                            "excesso": valor,
                        }
                        for chave, valor in excesso.items()
                    },
                })

    return {
        "somas_ok": somas_ok,
        "n_alimentos": n_alimentos,
        "incoerentes": incoerentes,
        "desvios": desvios,
        "limites_ok": not excedentes and not opcoes_excedentes,
        "excedentes": excedentes,
        "opcoes_excedentes": opcoes_excedentes,
    }

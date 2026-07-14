# -*- coding: utf-8 -*-
"""
motor.py — Motor de cálculo clínico e geração do cardápio
==========================================================

Lógica PURA (sem Streamlit, sem IA), seguindo o processo descrito em
"DOCUMENTO PARA CRIAÇÃO DO CARDÁPIO.md":

    1. TMB (Mifflin-St Jeor)
    2. GET = TMB × Fator de Atividade Física (FAF)
    3. Meta calórica final definida pela nutricionista (GET é referência)
    4. Metas de MACRO (Regras de Ouro do documento):
         - Proteína: g/kg de peso corporal       (ancorada primeiro)
         - Gordura : % das calorias totais
         - Carboidrato: preenche o restante das calorias
         - Fibra: meta informativa (~14 g / 1000 kcal)
    5. Geração do cardápio: usa o template da nutricionista como esqueleto de
       refeições e reescala a gramatura de cada alimento por MACRO (não por um
       fator calórico único), respeitando aversões/alergias (lógica de
       substituição "Isabela/Yuri" por regra de três).

Como cada alimento é arquivado com uma `categoria` (Carboidrato/Proteína/
Gordura/Outro), aplicamos um fator de escala POR MACRONUTRIENTE:

    fator_carb = meta_carb_g / (carb fornecido pelos alimentos-carboidrato)
    fator_prot = meta_prot_g / (prot fornecida pelos alimentos-proteína)
    fator_gord = meta_gord_g / (gord fornecida pelos alimentos-gordura)

Cada alimento é escalado pelo fator do macro que ele representa. Itens "Outro"
(café, temperos, vegetais livres) não são escalados. Como um alimento carrega
macros secundários, os totais finais não são exatos — por isso a função devolve
os TOTAIS ATINGIDOS vs as METAS, para a nutricionista conferir e ajustar.
"""

import json
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
    return {
        "nome": dados.get("nome_template", "Cardápio Base"),
        "calorias_totais": float(calorias),
        "refeicoes": dados.get("refeicoes", []),
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
    """TMB por Mifflin-St Jeor."""
    base = (10 * peso_kg) + (6.25 * altura_cm) - (5 * idade)
    return base + (5 if normalizar_texto(genero) == "masculino" else -161)


def calcular_metas(peso_kg, altura_cm, idade, genero, fator_atividade, objetivo,
                   ajuste_kcal=None, prot_g_kg=None, perc_gordura=PERC_GORDURA_PADRAO,
                   meta_kcal_manual=None):
    """Calcula TMB, GET, meta calórica e metas de macro.

    A meta calórica pode ser definida diretamente pela nutricionista. Quando
    `meta_kcal_manual` não é informado, o cálculo legado usa GET + ajuste_kcal.
    Proteína e gordura continuam ajustáveis para recalcular os macros.

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
    prot_g = prot_g_kg * peso_kg
    gord_g = (perc_gordura * meta_kcal) / 9.0
    kcal_restante = meta_kcal - (prot_g * 4) - (gord_g * 9)
    carb_g = max(kcal_restante, 0) / 4.0
    fibra_g = (meta_kcal / 1000.0) * 14.0  # recomendação informativa

    return {
        "tmb": round(tmb),
        "get": round(get),
        "ajuste_kcal": round(ajuste_kcal),
        "meta_kcal": round(meta_kcal),
        "prot_g_kg": prot_g_kg,
        "perc_gordura": perc_gordura,
        "meta_prot_g": round(prot_g, 1),
        "meta_gord_g": round(gord_g, 1),
        "meta_carb_g": round(carb_g, 1),
        "meta_fibra_g": round(fibra_g, 1),
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

    novo = dict(alimento)
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
    """Gera o cardápio ajustado por metas de macro.

    termos_excluidos: lista de strings (aversões ∪ alergias ∪ intolerâncias).
    opcao_por_slot: dict {slot: índice_da_opção} para escolher qual opção de
                    cada horário entra no cálculo (padrão: a 1ª de cada slot).

    Retorna (slots_resultado, totais, fatores, avisos).
    """
    termos_norm = [normalizar_texto(t) for t in termos_excluidos if t and t.strip()]
    grupos = agrupar_em_slots(template["refeicoes"])
    opcao_por_slot = opcao_por_slot or {}

    # Refeições que CONTAM para os totais (uma opção por slot).
    incluidas = []
    for slot, opcoes in grupos:
        idx = opcao_por_slot.get(slot, 0)
        idx = idx if 0 <= idx < len(opcoes) else 0
        incluidas.append(opcoes[idx])

    fatores, avisos = calcular_fatores_macro(metas, incluidas)

    totais = {"kcal": 0.0, "carboidratos_g": 0.0, "proteinas_g": 0.0, "gorduras_g": 0.0}
    slots_resultado = []

    for slot, opcoes in grupos:
        idx_incluida = opcao_por_slot.get(slot, 0)
        idx_incluida = idx_incluida if 0 <= idx_incluida < len(opcoes) else 0
        opcoes_result = []

        for i, refeicao in enumerate(opcoes):
            alimentos_finais = []
            for alimento in refeicao.get("alimentos", []):
                escalado = escalar_alimento(alimento, fatores)
                final, _ = aplicar_swap(escalado, banco, termos_norm)
                alimentos_finais.append(final)

                if i == idx_incluida:  # só a opção escolhida soma nos totais
                    totais["kcal"] += final.get("calorias", 0) or 0
                    for m in ("carboidratos_g", "proteinas_g", "gorduras_g"):
                        totais[m] += final.get("macros", {}).get(m, 0) or 0

            opcoes_result.append({
                "nome_refeicao": refeicao.get("nome_refeicao", "Refeição"),
                "horario": refeicao.get("horario"),
                "observacoes": refeicao.get("observacoes_da_refeicao"),
                "alimentos": alimentos_finais,
                "conta_no_total": (i == idx_incluida),
            })

        slots_resultado.append({"slot": slot, "opcoes": opcoes_result})

    totais = {k: round(v, 1) for k, v in totais.items()}
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


def descrever_porcao(alimento):
    """Texto amigável da porção: '60 g (≈ 2½ colheres de sopa)'.

    Usa a medida caseira do alimento (gramas_por_unidade) recalculada para a
    gramatura atual (já escalada). Sem medida conhecida, mostra só as gramas.
    """
    g = alimento.get("quantidade_g", 0) or 0
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

    return {
        "somas_ok": somas_ok,
        "n_alimentos": n_alimentos,
        "incoerentes": incoerentes,
        "desvios": desvios,
    }

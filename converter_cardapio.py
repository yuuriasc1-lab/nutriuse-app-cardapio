# -*- coding: utf-8 -*-
"""
converter_cardapio.py — Converte o plano alimentar em cardapio_base.json
========================================================================

Lê `referencias/cardapio/Plano_alimentar_base.txt`, que tem refeições com
alimentos e gramaturas, e gera `referencias/cardapio/cardapio_base.json`
estruturado COM MACROS por alimento (formato que o motor.py consome).

PRINCÍPIO (Documentação): não inventamos valores nutricionais. Os macros vêm de:
  1) Tabela curada derivada do cardapio_base.json ATUAL (manhã/treino já vetado).
  2) Correspondência no alimentos.json (TBCA) por similaridade de nomes.
Cada alimento recebe um nível de confiança; itens de baixa confiança são listados
em `referencias/relatorios/relatorio_conversao.txt` para revisão.

Uso:
    python converter_cardapio.py
Gera:
    referencias/cardapio/cardapio_base.json       (backup automático do anterior)
    referencias/relatorios/relatorio_conversao.txt
"""

import json
import os
import re
import shutil
import unicodedata
from datetime import datetime

import motor  # reusa normalizar_texto, numero_br_para_float, loaders TBCA

DIR = os.path.dirname(os.path.abspath(__file__))
DIR_REFERENCIAS = os.path.join(DIR, "referencias")
DIR_CARDAPIO = os.path.join(DIR_REFERENCIAS, "cardapio")
DIR_ALIMENTOS = os.path.join(DIR_REFERENCIAS, "alimentos")
DIR_RELATORIOS = os.path.join(DIR_REFERENCIAS, "relatorios")


def _primeiro_existente(caminhos, padrao=None):
    return next((c for c in caminhos if os.path.exists(c)), padrao or caminhos[0])


def _garantir_pastas():
    for caminho in (DIR_CARDAPIO, DIR_ALIMENTOS, DIR_RELATORIOS):
        os.makedirs(caminho, exist_ok=True)


# Fonte da verdade: o plano base que a nutricionista mantém (texto).
# Aceita 'Plano_alimentar_base.txt' (canônico) ou 'Plano_alimentar.txt' (legado).
TXT = _primeiro_existente([
    os.path.join(DIR_CARDAPIO, "Plano_alimentar_base.txt"),
    os.path.join(DIR_CARDAPIO, "Plano_alimentar.txt"),
    os.path.join(DIR, "Plano_alimentar_base.txt"),
    os.path.join(DIR, "Plano_alimentar.txt"),
], os.path.join(DIR_CARDAPIO, "Plano_alimentar_base.txt"))
JSON_SAIDA = os.path.join(DIR_CARDAPIO, "cardapio_base.json")
RELATORIO = os.path.join(DIR_RELATORIOS, "relatorio_conversao.txt")


# ---------------------------------------------------------------------------
# Categorização e itens "livres"
# ---------------------------------------------------------------------------

# Palavras que indicam alimento de consumo livre (sem gramatura / À vontade).
LIVRE_REGEX = re.compile(r"(à\s*vontade|a\s*vontade)", re.IGNORECASE)

# Heurística de categoria por palavras-chave do nome (fallback quando não há
# match curado/TBCA com categoria definida).
PALAVRAS_CATEGORIA = [
    ("Proteína", ["frango", "peito", "patinho", "carne", "bovina", "ovo", "clara",
                   "atum", "tilapia", "peixe", "whey", "iogurte", "queijo", "ricota",
                   "requeijao", "cottage", "leite", "lombo", "hamburguer", "sassami",
                   "mussarela", "creatina", "lombo suino"]),
    ("Gordura", ["castanha", "castanhas", "azeite", "oleo", "abacate", "pasta de castanha",
                 "amendoa", "nozes", "chia", "omegafor", "linhaça", "linhaca"]),
    ("Carboidrato", ["arroz", "feijao", "batata", "mandioca", "macarrao", "pao", "aveia",
                      "tapioca", "goma", "cuscuz", "banana", "mamao", "fruta", "frutas",
                      "morango", "abacaxi", "maca", "manga", "geleia", "bolacha", "torrada",
                      "rap 10", "biscoito", "milho", "abobora", "farinha", "farelo",
                      "suco", "polpa", "acai", "uva", "cacau"]),
]


def cat_por_heuristica(nome):
    n = motor.normalizar_texto(nome)
    for categoria, palavras in PALAVRAS_CATEGORIA:
        if any(p in n for p in palavras):
            return categoria
    return "Outro"


# ---------------------------------------------------------------------------
# 1. Tabela curada (por 100g) a partir do cardapio_base.json ATUAL
# ---------------------------------------------------------------------------

MACROS_CURADOS = os.path.join(DIR_ALIMENTOS, "macros_curados.json")


def carregar_curados_por_100g():
    """Carrega a tabela PRISTINA de macros por 100g (macros_curados.json).

    IMPORTANTE: esta tabela é a fonte curada de alimentos processados/de marca
    (whey, creme de ricota, pão de forma, geleia, etc.). Ela é SEPARADA do
    arquivo de saída (cardapio_base.json) — o conversor nunca lê a própria saída,
    evitando o laço de realimentação. Edite este arquivo à mão para corrigir/
    adicionar valores de rótulo.
    """
    if not os.path.exists(MACROS_CURADOS):
        legado = os.path.join(DIR, "macros_curados.json")
        if not os.path.exists(legado):
            return {}
        caminho = legado
    else:
        caminho = MACROS_CURADOS
    with open(caminho, encoding="utf-8") as f:
        dados = json.load(f)
    # Já vem no formato {chave_normalizada: {nome, categoria, por_100g}}.
    return dados


# ---------------------------------------------------------------------------
# 2. Índice TBCA para matching por similaridade
# ---------------------------------------------------------------------------

_STOPWORDS = {"de", "do", "da", "com", "sem", "e", "ou", "em", "no", "na", "a", "o",
              "s", "c", "para", "tipo", "cru", "crua"}


def _tokens(texto):
    n = motor.normalizar_texto(texto)
    n = re.sub(r"[^a-z0-9 ]", " ", n)
    return {t for t in n.split() if t and t not in _STOPWORDS and len(t) > 1}


# Palavras que denunciam PRATO COMPOSTO/RECEITA na TBCA — devem ser evitadas
# quando buscamos um ingrediente simples (in natura/preparo básico).
PALAVRAS_PRATO = ["molho a", "molho à", "bolonhesa", "salada,", "caesar", "polenta",
                  "capeleti", "capelete", "sopa", "sanduiche", "sanduíche", "pizza",
                  "torta", "lasanha", "risoto", "escondidinho", "nhoque", "panqueca",
                  "sufle", "suflê", "empada", "croquete", "bolinho", "estrogonofe",
                  "feijoada", "yakisoba", "refogad", "à bolonhesa", "recheado",
                  "recheada", "hamburguer", "hambúrguer", "wrap", "tabule", "kibe",
                  "quibe", "almondega", "almôndega", "nugget", "salgado", "pastel",
                  "coxinha", "bolo,", "pirarucu", "anchova"]


def _tem_palavra_prato(nome_norm):
    return any(p in nome_norm for p in PALAVRAS_PRATO)


def carregar_indice_tbca():
    banco = motor.carregar_banco_alimentos()
    indice = []
    for a in banco:
        if a["energia_kcal"] <= 0:
            continue
        nome_norm = motor.normalizar_texto(a["nome_alimento"])
        indice.append({
            "nome": a["nome_alimento"],
            "nome_norm": nome_norm,
            "tokens": _tokens(a["nome_alimento"]),
            "eh_prato": _tem_palavra_prato(nome_norm),
            "categoria": a["categoria"],
            "por_100g": {
                "kcal": a["energia_kcal"], "carb": a["carboidrato"],
                "prot": a["proteina"], "gord": a["lipidios"],
            },
        })
    return indice


# Estados de cocção que, se baterem, aumentam a confiança do match.
ESTADOS = ["cozid", "grelhad", "assad", "frit", "desfiad", "moid", "mexid", "cru"]


def melhor_match_tbca(nome, indice):
    """Retorna (registro, score 0..1) do melhor alimento TBCA para o nome.

    Penaliza pratos compostos e nomes longos (preferindo ingredientes simples).
    """
    alvo = _tokens(nome)
    if not alvo:
        return None, 0.0
    nome_norm = motor.normalizar_texto(nome)
    estados_alvo = [e for e in ESTADOS if e in nome_norm]
    # Só aceitamos prato composto se o próprio alvo também for um prato.
    alvo_eh_prato = _tem_palavra_prato(nome_norm)

    melhor, melhor_score = None, 0.0
    for reg in indice:
        if reg["eh_prato"] and not alvo_eh_prato:
            continue  # evita Polenta à bolonhesa quando buscamos "Patinho"
        inter = alvo & reg["tokens"]
        if not inter:
            continue
        cobertura = len(inter) / len(alvo)
        jaccard = len(inter) / len(alvo | reg["tokens"])
        score = 0.7 * cobertura + 0.3 * jaccard
        if estados_alvo and any(e in reg["nome_norm"] for e in estados_alvo):
            score += 0.1
        # Penaliza descrições longas (quanto mais tokens "a mais", pior o foco).
        excesso = max(0, len(reg["tokens"]) - len(alvo))
        score -= 0.02 * excesso
        if score > melhor_score:
            melhor, melhor_score = reg, min(max(score, 0), 1.0)
    return melhor, melhor_score


# ---------------------------------------------------------------------------
# 2b. Mapa CURADO de staples -> entrada TBCA correta (busca por tokens exigidos)
# ---------------------------------------------------------------------------
# Cada regra: (substring_no_nome_do_plano, [tokens_obrigatorios_na_TBCA], categoria).
# O macro vem da entrada TBCA mais SIMPLES que contém todos os tokens — valores
# reais da tabela, não inventados. Resolve os staples de almoço/jantar/lanche.
STAPLES = [
    ("arroz integral",       ["arroz", "integral", "cozid"],            "Carboidrato"),
    ("arroz branco",         ["arroz", "polido", "cozid"],              "Carboidrato"),
    ("arroz",                ["arroz", "polido", "cozid"],              "Carboidrato"),
    ("feijao carioca",       ["feijao", "carioca", "cozid"],            "Carboidrato"),
    ("feijao",               ["feijao", "cozid"],                       "Carboidrato"),
    ("batata doce",          ["batata", "doce", "cozid"],               "Carboidrato"),
    ("batata inglesa",       ["batata", "inglesa", "cozid", "dren"],    "Carboidrato"),
    ("batata baroa",         ["batata", "baroa", "cozid"],              "Carboidrato"),
    ("mandioca",             ["mandioca", "cozid", "dren"],             "Carboidrato"),
    ("macarrao integral",    ["macarrao", "cozid"],                     "Carboidrato"),
    ("macarrao",             ["macarrao", "cozid"],                     "Carboidrato"),
    ("abobora cabotian",     ["abobora", "cabotia", "cozid"],           "Carboidrato"),
    ("milho verde",          ["milho", "verde", "cozid"],               "Carboidrato"),
    ("cuscuz",               ["cuscuz", "milho"],                       "Carboidrato"),
    ("file de frango",       ["frango", "peito", "grelhad"],            "Proteína"),
    ("peito de frango grelhado", ["frango", "peito", "grelhad"],        "Proteína"),
    ("frango grelhado",      ["frango", "peito", "grelhad"],            "Proteína"),
    ("peito de frango cozido", ["frango", "peito", "cozid"],            "Proteína"),
    ("frango desfiado",      ["frango", "peito", "cozid"],              "Proteína"),
    ("peito de frango desfiado", ["frango", "peito", "cozid"],          "Proteína"),
    ("frango",               ["frango", "peito", "grelhad"],            "Proteína"),
    ("patinho",              ["patinho", "grelhad"],                    "Proteína"),
    ("carne bovina",         ["patinho", "grelhad"],                    "Proteína"),
    ("bife",                 ["patinho", "grelhad"],                    "Proteína"),
    ("tilapia",              ["tilapia", "cozid"],                      "Proteína"),
    ("lombo suino",          ["lombo", "suin", "assad"],                "Proteína"),
    ("atum",                 ["atum", "conserva"],                      "Proteína"),
    ("ovo de galinha",       ["ovo", "galinha", "inteiro", "cozid"],    "Proteína"),
    ("clara de ovo",         ["clara", "ovo", "cozid"],                 "Proteína"),
    ("cenoura",              ["cenoura", "crua"],                       "Outro"),
    ("tomate",               ["tomate", "cru"],                         "Outro"),
    ("brocolis",             ["brocolis", "cozid"],                     "Outro"),
    ("mix de castanhas",     ["castanha", "para"],                      "Gordura"),
    ("castanha de caju",     ["castanha", "caju"],                      "Gordura"),
    ("abacate",              ["abacate", "cru"],                        "Gordura"),
]


def buscar_tbca_tokens(indice, tokens_obrig):
    """Acha a entrada TBCA mais simples que contém TODOS os tokens (substring)."""
    cands = [r for r in indice
             if not r["eh_prato"] and all(t in r["nome_norm"] for t in tokens_obrig)]
    if not cands:
        # relaxa o último token (estado de cocção pode faltar)
        cands = [r for r in indice
                 if not r["eh_prato"] and all(t in r["nome_norm"] for t in tokens_obrig[:-1])]
    if not cands:
        return None
    cands.sort(key=lambda r: len(r["nome_norm"]))  # mais curta = mais "pura"
    return cands[0]


# Produtos processados cujo nome contém um ingrediente-staple (ex.: "Bolacha de
# arroz", "Torrada", "Farinha de aveia"): o macro deve vir da tabela CURADA (valor
# de rótulo), não do ingrediente cru da TBCA. Sem esta guarda, "bolacha de arroz"
# casaria o staple de arroz e viraria "arroz cozido" (34kcal/25g em vez de ~98).
MARCADORES_PROCESSADO = ("bolacha", "biscoito", "bolo", "torrada", "chips", "farinha")


def resolver_staple(nome, indice):
    """Se o nome casar um staple curado, devolve (registro_tbca, categoria)."""
    n = motor.normalizar_texto(nome)
    if any(m in n for m in MARCADORES_PROCESSADO):
        return None, None  # processado -> usa o curado, não o ingrediente cru
    for substr, tokens, categoria in STAPLES:
        if substr in n:
            reg = buscar_tbca_tokens(indice, tokens)
            if reg:
                return reg, categoria
    return None, None


# ---------------------------------------------------------------------------
# 3. Parsing do TXT
# ---------------------------------------------------------------------------

SEP = "=" * 80

# Cabeçalhos que NÃO são refeições (pular).
NAO_REFEICAO = ["ORIENTAÇÕES", "RECEITA:", "FIM DO DOCUMENTO",
                "PRESCRIÇÃO ALIMENTAR", "PLANEJAMENTO"]

# Linha de alimento: nome ......  gramatura. Capturamos o trecho final com a qtd.
LINHA_IGNORAR_PREFIXO = ("substitui", "modo de", "receita", "obs", "dica", "os ovos",
                          "sugest", "sugestão", "variação", "ingredientes", "molho com",
                          "ingredientes livres", "opção de prot", "opções de prot",
                          "opção prot", "use molho", "monte ", "guarde", "aqueça",
                          "para adoçar", "rendimento", "*", "(", "—", "-", "1)", "2)",
                          "3)", "4)", "5)", "sambazon")


def extrair_gramatura(linha):
    """Extrai (gramas:float, eh_livre:bool) de uma linha de alimento.

    Aceita: '80g', '100ml', '2 Fatias (50g)', '1 Colher café cheia (4g)',
    '1 Copo (200ml)', '25g (7 unidades)', '1 Fatia e 1/2 (38g)', 'À vontade'.
    Trata ml como ~g (água/leite). Itens livres -> (0, True).
    """
    if LIVRE_REGEX.search(linha):
        return 0.0, True
    # Procura todos os números seguidos de g/ml; prioriza o que está entre parênteses.
    candidatos = re.findall(r"(\d+(?:[.,]\d+)?)\s*(g|ml)\b", linha, re.IGNORECASE)
    if not candidatos:
        return None, False
    # Prefere uma medida dentro de parênteses (geralmente a gramatura real).
    paren = re.findall(r"\((?:[^()]*?)(\d+(?:[.,]\d+)?)\s*(g|ml)[^()]*\)", linha, re.IGNORECASE)
    valor = paren[-1][0] if paren else candidatos[0][0]
    return motor.numero_br_para_float(valor), False


def nome_do_alimento(linha):
    """Remove a parte de quantidade, deixando só o nome do alimento."""
    if LIVRE_REGEX.search(linha):
        # Em "Legumes (mínimo 100g)  À vontade", os 100 g fazem parte da
        # orientação do nome e não são a porção calculada do alimento.
        corte = re.split(
            r"\s{2,}|\bÀ\s*vontade|\ba\s*vontade", linha, maxsplit=1
        )[0]
        return corte.strip(" .:-")
    # Corta a partir do primeiro dígito de quantidade ou de muitos espaços.
    corte = re.split(r"\s{2,}|\s+\d|\bÀ\s*vontade|\ba\s*vontade", linha, maxsplit=1)[0]
    return corte.strip(" .:-")


def extrair_medida_caseira(linha, nome, gramas):
    """Extrai a medida caseira textual de uma linha, ex.: '2 Fatias', '1 Xícara'.

    Devolve (unidade_nome, gramas_por_unidade) ou (None, None) quando a linha só
    tem gramas (ex.: 'Banana 80g'). Usado para mostrar a porção de forma intuitiva.
    """
    idx = linha.find(nome)
    resto = linha[idx + len(nome):] if idx >= 0 else linha
    resto = resto.strip()
    if not resto:
        return None, None

    # Caso a gramatura esteja entre parênteses: medida fica fora deles.
    # Ex.: '2 Fatias (50g)' -> medida_txt='2 Fatias'
    paren = re.search(r"\([^()]*\d+(?:[.,]\d+)?\s*(?:g|ml)[^()]*\)", resto, re.IGNORECASE)
    if paren:
        medida_txt = (resto[:paren.start()] + resto[paren.end():]).strip(" .:-()")
    else:
        # Gramatura no início: '25g (7 unidades)' -> medida_txt='7 unidades'
        sem_g = re.sub(r"^\s*\d+(?:[.,]\d+)?\s*(?:g|ml)\b", "", resto, flags=re.IGNORECASE)
        medida_txt = sem_g.strip(" .:-()")

    # Sobrou só número/gramas ou vazio -> sem medida caseira útil.
    if not medida_txt or re.fullmatch(r"[\d.,\s/g(ml)]+", medida_txt, re.IGNORECASE):
        return None, None

    # Conta numérica no começo da medida (1, 2, '1 e 1/2'...).
    m = re.match(r"(\d+(?:[.,]\d+)?)(?:\s*e\s*(?:1/2|meia|meio))?\s*(.*)", medida_txt)
    if not m:
        return None, None
    count = motor.numero_br_para_float(m.group(1))
    if "e 1/2" in medida_txt.lower() or "e meia" in medida_txt.lower() or "e meio" in medida_txt.lower():
        count += 0.5
    unidade = m.group(2).strip(" .:-").rstrip("s") or "unidade"
    if count <= 0 or gramas <= 0:
        return None, None
    return unidade, round(gramas / count, 2)


def extrair_orientacoes(caminho):
    """Extrai a lista de orientações gerais da seção ORIENTAÇÕES NUTRICIONAIS."""
    with open(caminho, encoding="utf-8") as f:
        linhas = f.read().splitlines()
    orientacoes, dentro, buffer = [], False, ""
    i = 0
    while i < len(linhas):
        s = linhas[i].strip()
        if s.startswith("ORIENTA") and "NUTRICION" in s.upper():
            dentro = True
            i += 2  # pula o separador '===' abaixo do título
            continue
        if dentro and s == SEP:
            break  # fim da seção
        if dentro:
            if s.startswith("- "):
                if buffer:
                    orientacoes.append(buffer.strip())
                buffer = s[2:]
            elif s:
                buffer += " " + s  # continuação da orientação anterior
        i += 1
    if buffer:
        orientacoes.append(buffer.strip())
    return orientacoes


def extrair_substituicoes(corpo):
    """Extrai os blocos 'Substituições para X: ...' do corpo de uma refeição.

    Devolve dict {nome_alvo_normalizado: [opções...]}. As opções são strings
    cruas curadas pela nutricionista (ex.: 'Mamão - 200g', '15g Cottage').
    """
    subs = {}
    i, n = 0, len(corpo)
    while i < n:
        low = motor.normalizar_texto(corpo[i])
        m = re.match(r"substitui\w*\s+(?:para|de|do|da)\s+(.+?)\s*:?\s*$",
                     corpo[i].strip(), re.IGNORECASE)
        if low.startswith("substitui") and " para " in (" " + low + " ").replace(":", " "):
            # alvo = texto entre 'para' e ':' (sem parênteses de gramatura)
            cabecalho = corpo[i].strip()
            mcab = re.search(r"para\s+(.+?)\s*:", cabecalho, re.IGNORECASE)
            if mcab:
                alvo = re.sub(r"\([^)]*\)", "", mcab.group(1)).strip()
                # opções: resto da linha após ':' + linhas seguintes até blank/novo bloco
                resto = cabecalho.split(":", 1)[1] if ":" in cabecalho else ""
                texto = [resto]
                j = i + 1
                while j < n and corpo[j].strip() and not motor.normalizar_texto(
                        corpo[j]).startswith(("substitui", "modo", "obs", "receita",
                                              "sugest", "opcao", "opcoes", "variac",
                                              "os ovos", "dica", "use ", "monte")):
                    texto.append(corpo[j])
                    j += 1
                opcoes = []
                for parte in " ".join(texto).split("|"):
                    p = parte.strip(" .:-")
                    if p and not p.lower().startswith(("mesma", "lista", "substitu")):
                        opcoes.append(p)
                if opcoes:
                    subs[motor.normalizar_texto(alvo)] = opcoes
                i = j
                continue
        i += 1
    return subs


def parse_txt(caminho):
    """Lê o TXT e devolve lista de refeições com alimentos, medidas e substituições.

    Cada refeição: {nome, alimentos:[dict], substituicoes:{alvo_norm:[opções]}}.
    Cada alimento: {nome, gramas, livre, medida_unidade, gramas_por_unidade}.
    """
    with open(caminho, encoding="utf-8") as f:
        linhas = f.read().splitlines()

    refeicoes = []
    i = 0
    n = len(linhas)
    while i < n:
        if linhas[i].strip() == SEP and i + 1 < n:
            titulo = linhas[i + 1].strip()
            i += 2
            if i < n and linhas[i].strip() == SEP:
                i += 1
            corpo = []
            while i < n and linhas[i].strip() != SEP:
                corpo.append(linhas[i])
                i += 1
            if any(titulo.upper().startswith(p) for p in NAO_REFEICAO):
                continue

            substituicoes = extrair_substituicoes(corpo)
            alimentos = []
            for linha in corpo:
                bruto = linha.strip()
                if not bruto or "|" in bruto:
                    continue
                low = motor.normalizar_texto(bruto)
                if any(low.startswith(p) for p in LINHA_IGNORAR_PREFIXO):
                    continue
                if low.startswith(("--- ou", "variac", "1 un", "2 un", "3 un",
                                   "opcao prot", "opcao de prot", "opcoes de prot",
                                   "espeto de carne", "espeto de tilapia")) or low == "ou":
                    continue
                if re.match(r"^[\wÀ-ÿ ]+\s[-–]\s*\d", bruto):
                    continue
                gram, livre = extrair_gramatura(bruto)
                if gram is None and not livre:
                    continue
                nome = nome_do_alimento(bruto)
                if not nome or len(nome) < 2:
                    continue
                unidade, g_por_un = extrair_medida_caseira(bruto, nome, gram or 0.0)
                alimentos.append({
                    "nome": nome, "gramas": gram or 0.0, "livre": livre,
                    "medida_unidade": unidade, "gramas_por_unidade": g_por_un,
                    "orientacao_paciente": "À vontade" if livre else "",
                })
            if alimentos:
                refeicoes.append({"nome": titulo, "alimentos": alimentos,
                                  "substituicoes": substituicoes})
        else:
            i += 1
    return refeicoes


# ---------------------------------------------------------------------------
# 4. Resolução de macros por alimento
# ---------------------------------------------------------------------------

def resolver_macros(nome, gramas, livre, curados, indice):
    """Devolve (dict_alimento, confianca_str) no formato do cardapio_base.json."""
    chave = motor.normalizar_texto(nome)

    if livre or gramas <= 0:
        return _montar(nome, gramas, "Outro", 0, 0, 0, 0), "livre/0g"

    f = gramas / 100.0

    # 1) STAPLE -> entrada TBCA correta (arroz, feijão, frango, patinho, batata,
    #    cenoura...). Roda PRIMEIRO para esses alimentos in natura sempre virem
    #    frescos da TBCA, sem depender de valores curados.
    reg_st, cat_st = resolver_staple(nome, indice)
    if reg_st:
        p = reg_st["por_100g"]
        al = _montar(nome, gramas, cat_st,
                     p["kcal"]*f, p["carb"]*f, p["prot"]*f, p["gord"]*f)
        al["match_tbca"] = reg_st["nome"]
        return al, "ALTA (staple)"

    # 2) curado exato (processados/marca: whey, ricota, pão de forma, geleia...)
    if chave in curados:
        p = curados[chave]["por_100g"]
        return _montar(nome, gramas, curados[chave]["categoria"],
                       p["kcal"]*f, p["carb"]*f, p["prot"]*f, p["gord"]*f), "ALTA (curado)"

    # 3) curado parcial (contenção de tokens)
    for ckey, c in curados.items():
        if ckey and (ckey in chave or chave in ckey) and len(ckey) > 3:
            p = c["por_100g"]
            return _montar(nome, gramas, c["categoria"],
                           p["kcal"]*f, p["carb"]*f, p["prot"]*f, p["gord"]*f), "MÉDIA (curado~)"

    # 4) TBCA por similaridade
    reg, score = melhor_match_tbca(nome, indice)
    if reg and score >= 0.45:
        p = reg["por_100g"]; f = gramas / 100.0
        conf = "MÉDIA (TBCA %.0f%%)" % (score*100) if score < 0.7 else "ALTA (TBCA %.0f%%)" % (score*100)
        al = _montar(nome, gramas, reg["categoria"],
                     p["kcal"]*f, p["carb"]*f, p["prot"]*f, p["gord"]*f)
        al["match_tbca"] = reg["nome"]
        return al, conf

    # 4) sem match — macros 0, categoria por heurística, REVISAR
    return _montar(nome, gramas, cat_por_heuristica(nome), 0, 0, 0, 0), "BAIXA (sem match)"


def _montar(nome, gramas, categoria, kcal, carb, prot, gord):
    return {
        "nome_principal": nome,
        "quantidade_g": round(gramas, 1),
        "categoria": categoria,
        "calorias": round(kcal, 1),
        "macros": {
            "carboidratos_g": round(carb, 1),
            "proteinas_g": round(prot, 1),
            "gorduras_g": round(gord, 1),
        },
        "medida_unidade": None,          # ex.: "Fatia", "Unidade média"
        "gramas_por_unidade": None,      # gramas de 1 unidade da medida caseira
        "opcoes_de_substituicao_listadas": [],
    }


# Tabela de referência de medidas caseiras para alimentos SEM medida no texto
# (banana, arroz, frango...). Editável à mão em medidas_caseiras.json.
MEDIDAS_REF = os.path.join(DIR_ALIMENTOS, "medidas_caseiras.json")


def carregar_medidas_ref():
    caminho = MEDIDAS_REF
    if not os.path.exists(caminho):
        legado = os.path.join(DIR, "medidas_caseiras.json")
        if not os.path.exists(legado):
            return {}
        caminho = legado
    if not os.path.exists(caminho):
        return {}
    with open(caminho, encoding="utf-8") as f:
        return json.load(f)


def medida_de_referencia(nome, ref):
    """Busca medida caseira de referência por nome (exato ou parcial)."""
    chave = motor.normalizar_texto(nome)
    if chave in ref:
        return ref[chave]["unidade"], ref[chave]["gramas_por_unidade"]
    for k, v in ref.items():
        if k and (k in chave or chave in k) and len(k) > 3:
            return v["unidade"], v["gramas_por_unidade"]
    return None, None


def casar_substituicoes(nome, subs_dict):
    """Retorna a lista de substituições curadas para o alimento, se houver."""
    chave = motor.normalizar_texto(nome)
    for alvo, opcoes in subs_dict.items():
        if alvo and (alvo in chave or chave in alvo) and len(alvo) > 2:
            return opcoes
    return []


# ---------------------------------------------------------------------------
# 5. Orquestração
# ---------------------------------------------------------------------------

def main():
    _garantir_pastas()

    if not os.path.exists(TXT):
        raise SystemExit(f"Não encontrei {TXT}")

    curados = carregar_curados_por_100g()
    indice = carregar_indice_tbca()
    medidas_ref = carregar_medidas_ref()
    refeicoes_txt = parse_txt(TXT)

    refeicoes_json = []
    relatorio = [f"RELATÓRIO DE CONVERSÃO — {datetime.now():%d/%m/%Y %H:%M}",
                 "Confira especialmente os itens marcados BAIXA/MÉDIA.\n"]
    contagem = {"ALTA": 0, "MÉDIA": 0, "BAIXA": 0, "livre": 0}
    total_kcal = 0

    for ref in refeicoes_txt:
        alimentos_json = []
        relatorio.append(f"\n### {ref['nome']}")
        kcal_ref = 0
        for a in ref["alimentos"]:
            nome, gramas, livre = a["nome"], a["gramas"], a["livre"]
            al, conf = resolver_macros(nome, gramas, livre, curados, indice)

            # Medida caseira: do texto, ou da tabela de referência.
            unidade, gpu = a["medida_unidade"], a["gramas_por_unidade"]
            if not unidade:
                unidade, gpu = medida_de_referencia(nome, medidas_ref)
            al["medida_unidade"] = unidade
            al["gramas_por_unidade"] = gpu
            if a.get("orientacao_paciente"):
                al["orientacao_paciente"] = a["orientacao_paciente"]

            # Substituições curadas da nutricionista para este alimento.
            al["opcoes_de_substituicao_listadas"] = casar_substituicoes(
                nome, ref.get("substituicoes", {}))

            alimentos_json.append(al)
            kcal_ref += al["calorias"]
            chave_conf = ("ALTA" if conf.startswith("ALTA") else
                          "MÉDIA" if conf.startswith("MÉDIA") else
                          "livre" if conf.startswith("livre") else "BAIXA")
            contagem[chave_conf] += 1
            extra = f"  -> TBCA: {al['match_tbca']}" if al.get("match_tbca") else ""
            relatorio.append(f"  [{conf}] {nome} ({al['quantidade_g']}g) "
                             f"= {al['calorias']}kcal{extra}")
        total_kcal += kcal_ref
        refeicoes_json.append({
            "nome_refeicao": ref["nome"],
            "horario": None,
            "observacoes_da_refeicao": None,
            "alimentos": alimentos_json,
        })

    # Totais aproximados (apenas as opções; o motor depois resolve opção por slot).
    cardapio = {
        "nome_template": "Cardápio Base Padrão (convertido do Plano_alimentar.txt)",
        "calorias_totais_estimadas": round(total_kcal),
        "origem": os.path.relpath(TXT, DIR),
        "convertido_em": datetime.now().isoformat(timespec="seconds"),
        "orientacoes_gerais_do_cardapio": extrair_orientacoes(TXT),
        "refeicoes": refeicoes_json,
    }

    # Backup do JSON anterior.
    if os.path.exists(JSON_SAIDA):
        shutil.copy2(JSON_SAIDA, JSON_SAIDA + ".bak")

    with open(JSON_SAIDA, "w", encoding="utf-8") as f:
        json.dump(cardapio, f, ensure_ascii=False, indent=2)

    relatorio.insert(2, f"Refeições: {len(refeicoes_json)} | "
                        f"Confiança -> ALTA {contagem['ALTA']}, MÉDIA {contagem['MÉDIA']}, "
                        f"BAIXA {contagem['BAIXA']}, livre {contagem['livre']}\n")
    with open(RELATORIO, "w", encoding="utf-8") as f:
        f.write("\n".join(relatorio))

    print(f"OK — {len(refeicoes_json)} refeições, ~{round(total_kcal)} kcal somando todas as opções.")
    print(f"Confiança: ALTA {contagem['ALTA']} | MÉDIA {contagem['MÉDIA']} | "
          f"BAIXA {contagem['BAIXA']} | livre {contagem['livre']}")
    print(f"Backup: {JSON_SAIDA}.bak | Relatório: {RELATORIO}")


if __name__ == "__main__":
    main()

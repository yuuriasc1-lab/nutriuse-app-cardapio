# -*- coding: utf-8 -*-
"""Checklist de revisao antes de exportar o cardapio."""

import motor
import preparos
import regras_clinicas


def _desvio_abs_pct(desvios, chave):
    item = desvios.get(chave, {})
    return abs(item.get("pct", 0))


def _alertas_substituicoes(slots):
    alertas = []
    for grupo in slots or []:
        for opcao in grupo.get("opcoes", []):
            if not opcao.get("conta_no_total"):
                continue
            for al in opcao.get("alimentos", []):
                if al.get("substituicao_automatica"):
                    alertas.append({
                        "severidade": "alta",
                        "titulo": "Substituicao automatica pendente",
                        "descricao": (
                            f"{grupo.get('slot')}: {al.get('nome_original')} -> "
                            f"{al.get('nome_principal')} ({al.get('quantidade_g', 0):.0f} g)."
                        ),
                    })
                if al.get("alertas_substituicao"):
                    alertas.append({
                        "severidade": "media",
                        "titulo": "Alerta da substituicao",
                        "descricao": (
                            f"{grupo.get('slot')}: {al.get('nome_principal')} - "
                            + ", ".join(al.get("alertas_substituicao", []))
                        ),
                    })
    return alertas


def _alertas_metas(slots, totais, metas):
    validacao = motor.validar_resultado(slots, totais, metas)
    alertas = []
    for chave, titulo in [
        ("kcal", "Calorias"),
        ("carboidratos_g", "Carboidrato"),
        ("proteinas_g", "Proteina"),
        ("gorduras_g", "Gordura"),
    ]:
        pct = _desvio_abs_pct(validacao["desvios"], chave)
        if pct >= 30:
            nivel = "alta"
        elif pct >= 15:
            nivel = "media"
        else:
            continue
        d = validacao["desvios"][chave]
        alertas.append({
            "severidade": nivel,
            "titulo": f"{titulo} distante da meta",
            "descricao": f"Atingido {d['atingido']:.0f} vs meta {d['meta']:.0f} ({d['pct']:+d}%).",
        })
    return alertas


def _alertas_preparos(slots, selecionados=None, incluir_preparos=False, preparos_curados=None):
    if not incluir_preparos:
        return []
    sel = set(selecionados or [])
    alertas = []
    for si, grupo in enumerate(slots or []):
        for oi, opcao in enumerate(grupo.get("opcoes", [])):
            if sel and (si, oi) not in sel:
                continue
            if not sel and not opcao.get("conta_no_total"):
                continue
            if preparos.buscar_preparos(opcao, preparos_curados):
                continue
            nome = opcao.get("nome_refeicao", grupo.get("slot", "Refeicao"))
            if any(p in preparos.normalizar_texto(nome) for p in ("receita", "toast", "crepioca", "omelete", "acai")):
                nivel = "media"
            else:
                nivel = "baixa"
            alertas.append({
                "severidade": nivel,
                "titulo": "Preparo nao encontrado",
                "descricao": f"{nome}: sem modo de preparo curado associado.",
            })
    return alertas


def revisar_cardapio(metas, slots, totais, anamnese, regras_ativas=None,
                     selecionados=None, incluir_preparos=False, preparos_curados=None):
    regras_ativas = regras_ativas or regras_clinicas.avaliar_anamnese(anamnese)
    alertas = []

    for item in regras_clinicas.avaliar_cardapio(slots, regras_ativas):
        alertas.append({
            "severidade": item.get("severidade", "media"),
            "titulo": f"{item.get('regra')}: alimento para revisar",
            "descricao": (
                f"{item.get('refeicao')}: {item.get('alimento')} "
                f"({', '.join(item.get('termos', []))}). {item.get('mensagem', '')}"
            ),
        })

    alertas.extend(_alertas_substituicoes(slots))
    alertas.extend(_alertas_metas(slots, totais, metas))
    alertas.extend(_alertas_preparos(slots, selecionados, incluir_preparos, preparos_curados))

    ordem = {"critica": 4, "alta": 3, "media": 2, "baixa": 1}
    alertas.sort(key=lambda a: -ordem.get(a.get("severidade", "baixa"), 1))
    return {
        "alertas": alertas,
        "tem_critico": any(a.get("severidade") == "critica" for a in alertas),
        "tem_alta": any(a.get("severidade") == "alta" for a in alertas),
    }

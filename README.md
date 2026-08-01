# App Cardápio Marcela

Aplicativo Streamlit para a Marcela construir, ajustar, revisar e exportar
cardápios com o mínimo de alterações manuais.

- O cardápio da Marcela é a base principal e tem sua estrutura preservada.
- TBCA e bases complementares servem apenas para trocas e adições pontuais.
- A TMB usa Harris-Benedict revisada (1984); o GET é apenas uma referência.
- A Marcela define tetos exatos de kcal, proteína, carboidrato e gordura.
- Os quatro campos são vinculados: alterar kcal reescala todos os macros e
  alterar um macro redistribui automaticamente os outros dois.
- Ao editar uma porção, o alimento alterado fica como âncora e os demais itens
  da opção são readequados automaticamente; alimentos em 0 g continuam
  disponíveis para reativação e troca.
- Porções profissionais mantêm uma casa decimal.
- Saladas e legumes aceitam uma orientação textual para o paciente (por
  exemplo, "À vontade" ou "mínimo 100 g") ou uma quantidade numérica.
- A exportação do paciente usa porções terminadas em 0 ou 5. Se houver valores
  acima dos limites, o app mostra o atingido, o limite e o excesso e solicita
  confirmação, sem impedir a exportação.
- Cardápios podem ser salvos em JSON editável e importados posteriormente.

## Como rodar

```powershell
pip install -r requirements.txt
streamlit run app.py
```

Para usar a leitura por IA, informe a chave Gemini na barra lateral do app ou
configure `GEMINI_API_KEY` em `.streamlit/secrets.toml`.

## Regra das bases de dados

`referencias/cardapio/cardapio_base.json` é a fonte canônica. A geração mantém os
nomes dos alimentos, as refeições e as opções definidas pela Marcela, alterando
somente as quantidades para atender aos limites escolhidos.

O banco TBCA em `referencias/alimentos/alimentos.json` não substitui
automaticamente o cardápio-base. Ele é consultado somente quando a nutricionista
faz uma troca/adição ou quando uma restrição clínica exige uma substituição.

## Organizacao das referencias

```text
docs/
  Documentação.md
  DOCUMENTO PARA CRIAÇÃO DO CARDÁPIO.md

referencias/
  cardapio/
    Plano_alimentar_base.txt
    cardapio_base.json
    cardapio_base.json.bak
  alimentos/
    alimentos.json
    alimentos.txt
    macros_curados.json
    medidas_caseiras.json
  preparos/
    preparos_curados.json
  prompts/
    anamnese.md
    comando_cardapio.md
    preparo.md
    revisao_clinica.md
  regras/
    regras_clinicas.json
  tabelas_complementares/
    TACO_...
    TBCA_...
    Resposta_Glicemica...
  relatorios/
    relatorio_conversao.txt

logs/
  streamlit_log.txt
```

## Arquivos principais

- `app.py`: interface Streamlit e fluxo de revisao/exportacao.
- `motor.py`: calculos, metas manuais, geracao do cardapio e substituicoes automaticas.
- `cardapio_io.py`: pacote JSON seguro para salvar e reabrir cardápios em edição.
- `anamnese_ia.py`: extracao de anamnese por Gemini.
- `comando_ia.py`: interpretacao de comandos em linguagem natural.
- `ia_servico.py`: cliente central de IA para respostas JSON.
- `regras_clinicas.py`: aplica regras deterministicas de doencas/restricoes.
- `preparos.py`: associa modos de preparo curados e gera rascunhos por IA.
- `revisor_cardapio.py`: checklist antes da exportacao.
- `converter_cardapio.py`: converte `referencias/cardapio/Plano_alimentar_base.txt`
  em `referencias/cardapio/cardapio_base.json`.
- `validar_calculos.py`: valida formulas, somas, Atwater e determinismo das
  substituicoes.

## Camadas de IA e revisao

- A IA lê a anamnese e interpreta comandos, mas não calcula macros.
- A geracao usa a meta calorica final aprovada na tela de revisao; GET e ajuste
  sao informativos para apoiar a decisao clinica.
- Regras clinicas ficam em `referencias/regras/regras_clinicas.json` e podem
  gerar alertas ou adicionar termos aos filtros alimentares.
- Modos de preparo curados ficam em `referencias/preparos/preparos_curados.json`.
- Rascunhos de preparo por IA sao opcionais e aparecem marcados como rascunho
  para revisao.
- Antes do download, o app mostra um checklist com alertas clinicos, substituicoes
  automaticas pendentes, desvios de meta e preparos ausentes.

## Fluxo para atualizar o cardapio base

1. Edite `referencias/cardapio/Plano_alimentar_base.txt`.
2. Se necessario, ajuste alimentos de rotulo em
   `referencias/alimentos/macros_curados.json`.
3. Rode:

```powershell
python -X utf8 -B converter_cardapio.py
```

O conversor atualiza `referencias/cardapio/cardapio_base.json`, cria backup do
JSON anterior e grava a auditoria em `referencias/relatorios/relatorio_conversao.txt`.

## Validacao

O conjunto de validações também confirma que a geração sem filtros preserva
todos os alimentos e opções do cardápio-base da Marcela.

```powershell
python -X utf8 -B validar_calculos.py
```

Use `-X utf8` no Windows para evitar erro de codificacao ao imprimir simbolos no
terminal.

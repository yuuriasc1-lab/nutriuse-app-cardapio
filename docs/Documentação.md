# Documentação do Sistema: Automação de Prescrição Dietética (MVP)

## 1. Visão Geral do Sistema
O objetivo deste projeto é automatizar a etapa de cálculo de macronutrientes e seleção primária de alimentos para a elaboração de cardápios. O sistema atuará como um "Copiloto Clínico", recebendo os dados de anamnese, cruzando-os com o banco de dados da TBCA (Tabela Brasileira de Composição de Alimentos) e gerando um esboço estruturado da dieta, que será revisado e inserido no sistema final (WebDiet) pela nutricionista.

---

## 2. Arquitetura de Dados

### 2.1. Entidade de Entrada: Paciente (Anamnese)
Dados extraídos do prontuário em texto livre via IA:
* **Métricas Básicas:** Idade, Peso Atual (kg), Altura (cm), Gênero.
* **Objetivo Clínico:** Emagrecimento, Hipertrofia ou Manutenção.
* **Nível de Atividade Física:** Fator multiplicador (FAF).
* **Filtros de Restrição:**
  * Patologias (ex: Diabetes, Hipertensão).
  * Alergias/Intolerâncias (ex: Lactose, Glúten).
  * Aversões (Alimentos estritamente proibidos).
* **Preferências:** Alimentos "inegociáveis" que devem ser priorizados.
* **Estrutura de Refeições:** Número de refeições diárias e horários.

### 2.2. Entidade de Domínio: Banco de Alimentos (TBCA)
A Fonte da Verdade. O sistema não deve inventar dados nutricionais. Consultará exclusivamente um arquivo estruturado (JSON/CSV) com a seguinte estrutura para cada 100g do alimento:
* `id_alimento`
* `nome_alimento`
* `calorias_kcal`
* `carboidratos_g`
* `proteinas_g`
* `gorduras_g`
* `fibras_g`
* `medida_caseira_padrao` (ex: 1 escumadeira, 1 colher de sopa)

---

## 3. Lógica e Motor de Cálculo

### 3.1. Cálculo da Taxa Metabólica Basal (TMB)
*(Nota para a Nutricionista: O sistema utilizará Mifflin-St Jeor como padrão, sujeito a alteração conforme preferência clínica).*

Para Homens:
$$TMB = (10 \times peso) + (6.25 \times altura) - (5 \times idade) + 5$$

Para Mulheres:
$$TMB = (10 \times peso) + (6.25 \times altura) - (5 \times idade) - 161$$

### 3.2. Gasto Energético Total (GET) e Meta
* **GET:** TMB multiplicada pelo Fator de Atividade Física (FAF - variando de 1.2 para sedentários até 1.9 para atletas).
* **Meta Calórica Final:** definida pela nutricionista no perfil do paciente antes da geração do cardápio.
* **Ajuste vs GET:** exibido apenas como referência clínica. O sistema não escolhe automaticamente déficit, manutenção ou superávit.

### 3.3. Distribuição de Macronutrientes (Regras de Ouro)
1. **Meta calórica:** ajustada manualmente antes da geração; os macros são recalculados em tempo real.
2. **Proteínas:** fixadas prioritariamente baseadas no peso corporal (ex: 2.0g/kg para hipertrofia; 1.5g/kg para manutenção).
3. **Gorduras:** calculadas como percentual das calorias totais diárias.
4. **Carboidratos:** preenchem o restante da cota calórica disponível.

### 3.4. Regra de Substituição Proporcional (A "Lógica Isabela/Yuri")
Quando a cota de macronutrientes da refeição exige uma quantidade incompatível ou indesejada de um alimento, o sistema aciona a Regra de Substituição:

* **O Problema:** Atingir 21g de carboidrato exige 200g de mamão. Para atingir 50g, seriam necessários 470g de mamão (volume irreal para consumo ou alimento com aversão relatada).
* **A Ação do Sistema:**
  1. Identificar aversão/limite de volume.
  2. Isolar o macronutriente alvo daquela refeição (ex: 50g de Carboidrato).
  3. Consultar o banco TBCA por um alimento substituto do mesmo grupo (ex: Arroz Branco ou Banana).
  4. Recalcular a gramatura exata do novo alimento para bater os 50g do macro alvo, ajustando a medida caseira na saída.

---

## 4. Limitações Atuais (Restrições de Escopo)

### 4.1. Ausência de API Aberta no WebDiet
* **Situação:** O WebDiet é um ecossistema fechado. Não permite integração direta via código para popular os cardápios automaticamente no perfil do paciente.
* **Solução Paliativa (MVP):** O sistema gerará o cardápio em formato de texto limpo e estruturado (Markdown ou Google Docs). A nutricionista utilizará a estratégia de "Humano no Loop", revisando o texto e replicando/selecionando os itens manualmente no WebDiet (ou acionando modelos prontos do sistema).

### 4.2. Risco de Alucinação da Inteligência Artificial
* **Situação:** IAs generativas tendem a aproximar valores matemáticos ou inventar combinações alimentares incomuns caso não sejam restritas.
* **Solução:** * A temperatura do modelo (LLM) será configurada próxima a `0.0` para cálculos.
  * Injeção de "System Prompt" estrito: *É terminantemente proibido utilizar valores nutricionais fora da tabela TBCA fornecida.*

### 4.3. Dependência de Revisão Humana
* **Situação:** A IA não possui registro no CRN e não substitui o raciocínio clínico para nuances comportamentais e exames bioquímicos complexos.
* **Solução:** A automação é classificada como uma ferramenta de **Apoio à Decisão e Redução de Trabalho Braçal**. A responsabilidade pela prescrição final e adequação (ex: observar se a IA sugeriu colocar feijão no café da manhã para bater a meta de proteínas) permanece integralmente com a nutricionista.

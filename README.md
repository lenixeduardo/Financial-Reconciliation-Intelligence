# Financial Reconciliation Intelligence

Aplicação para conciliar duas bases financeiras com regras determinísticas, matching agrupado, revisão humana e exportação auditável.

> Regra central: **código concilia; IA não altera valores contábeis**. A camada de IA ficará restrita a sugestão de mapeamento e explicação de exceções em milestones posteriores.

## MVP 0.3 — templates persistentes + matching 1:1, 1:N e N:1

```text
Base A (ERP / razão / recebíveis)
            +
Base B (banco / adquirente / parceiro)
            ↓
          Upload
            ↓
     Detecção de colunas
            ↓
     Mapeamento confirmado
            ↓
     Template salvo/aplicado
            ↓
     Regras de tolerância
            ↓
      Matching Engine
       ├── 1:1
       ├── 1:N
       └── N:1
            ↓
  ┌──────────────────────┐
  │ MATCH                │
  │ PROBABLE_MATCH       │
  │ DIVERGENCE           │
  │ UNMATCHED            │
  │ DUPLICATE            │
  └──────────────────────┘
            ↓
       Revisão humana
            ↓
        Exportação CSV
```

## O que mudou na v0.3

### Templates de conciliação

Uma configuração recorrente agora pode ser salva com:

- nome e descrição do processo;
- mapeamento da base principal;
- mapeamento da base comparada;
- tolerância de valor e data;
- similaridade textual;
- regras de documento;
- configuração de matching 1:N / N:1;
- limiares de confiança.

Exemplo: configure `ERP × Itaú` uma vez e, no fechamento seguinte, suba as novas bases e aplique o template antes de executar.

O backend valida se as colunas exigidas pelo template existem nas novas bases. Se houver incompatibilidade, retorna exatamente quais colunas estão ausentes em vez de executar uma regra incorreta.

Os templates podem ser criados, listados, atualizados, aplicados e excluídos pela interface e API.

## Matching agrupado da v0.2

### 1:N — um lançamento contra vários

Exemplo: o ERP possui um recebível de R$ 1.000 e o banco recebeu duas parcelas de R$ 600 + R$ 400. O motor procura uma combinação cuja soma respeite a tolerância configurada e valida data, descrição e documento quando esses campos estiverem mapeados.

### N:1 — vários lançamentos contra um

Exemplo: três títulos do ERP foram liquidados em um único crédito bancário. O motor agrupa as linhas da base principal e compara a soma ao lançamento único da base de comparação.

### Auditoria do grupo

Cada resultado passa a registrar:

- `match_cardinality`: `1:1`, `1:N` ou `N:1`;
- todos os `left_indices` e `right_indices` consumidos;
- linhas originais que compõem o grupo;
- soma de cada lado;
- diferença agrupada;
- confiança e motivos da classificação.

Um registro consumido por um grupo não pode ser reutilizado em outro match.

## Funcionalidades

- Upload de CSV e XLSX.
- Preview e sugestão automática de mapeamento por nomes de colunas.
- Mapeamento de valor, data, descrição e documento.
- Tolerância monetária configurável.
- Janela de tolerância de datas.
- Similaridade textual com `SequenceMatcher`.
- Matching 1:1 composto com score de confiança.
- **Matching 1:N e N:1 determinístico por soma de valores.**
- Templates persistentes de mapeamento e regras.
- Validação de compatibilidade do template contra novas bases.
- Tamanho máximo do agrupamento configurável entre 2 e 5 registros.
- Limiar mínimo de confiança específico para grupos.
- Proteção contra reutilização de linhas.
- Detecção de duplicidades quando há identificador documental mapeado.
- Revisão manual de matches prováveis e divergências.
- Persistência local em SQLite.
- Exportação CSV incluindo cardinalidade e índices do grupo.
- Interface mobile-first, light mode padrão e dark mode opcional.
- API FastAPI documentada automaticamente em `/docs`.

## Ordem do motor

O processamento segue uma ordem deliberada para evitar falsos agrupamentos:

```text
1. Duplicidades com identificador confiável
        ↓
2. Matches 1:1 exatos e fortes
        ↓
3. Matches agrupados 1:N / N:1
        ↓
4. Matches 1:1 aproximados / divergentes
        ↓
5. Não encontrados
```

## Regras novas

```json
{
  "group_matching_enabled": true,
  "max_group_size": 3,
  "group_match_threshold": 0.85,
  "group_candidate_limit": 18
}
```

`group_candidate_limit` limita o universo analisado por registro para manter o custo combinatório controlado no MVP.

## Stack

```text
Frontend     React + TypeScript + Vite + Lucide
Backend      Python + FastAPI + Pydantic
Engine       Matching determinístico em Python
Arquivos     CSV + XLSX / openpyxl
Persistência SQLite no MVP
Infra        Docker Compose
```

## Executar com Docker

```bash
docker compose up --build
```

- Interface: `http://localhost:3000`
- API: `http://localhost:8000`
- Swagger: `http://localhost:8000/docs`

## Backend sem Docker

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
uvicorn app.main:app --reload
```

## Testes

```bash
cd backend
pytest -q
```

A v0.3 possui testes para:

- match exato;
- divergência;
- unmatched;
- duplicidades;
- 1:N;
- N:1;
- agrupamento desativado;
- não reutilização de linhas;
- fluxo HTTP completo;
- exportação e health check.
- criação, listagem, atualização e exclusão de templates;
- aplicação compatível e detecção de colunas ausentes.

## API principal

```text
POST /datasets/upload
GET  /templates
POST /templates
GET  /templates/{id}
PUT  /templates/{id}
DELETE /templates/{id}
POST /templates/{id}/apply
POST /reconciliations
GET  /reconciliations/{id}
POST /reconciliations/{id}/pairs/{pair_id}/decision
GET  /reconciliations/{id}/export.csv
GET  /health
```

## Limite atual do matching agrupado

O algoritmo faz busca combinatória controlada por `max_group_size` e `group_candidate_limit`. É adequado para o MVP e bases moderadas. Para milhões de linhas, a próxima evolução técnica é gerar candidatos previamente com Polars/DuckDB e usar técnicas de subset-sum/indexação antes da avaliação fina.

## Próximas evoluções possíveis

1. Polars/DuckDB para grandes volumes.
2. PostgreSQL e processamento assíncrono.
3. IA para sugerir mapeamentos e explicar exceções, sem decidir valores.
4. Observabilidade de runs e auditoria de decisões humanas.

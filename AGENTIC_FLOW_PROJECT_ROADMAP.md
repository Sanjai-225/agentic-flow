# Agentic Flow --- Project Overview, Architecture and Development Roadmap

> **Document purpose:** A shared project-understanding and
> implementation-planning document for the Agentic Flow team.\
> **Status:** Living document --- phases, module ownership, technologies
> and implementation order may change as the project evolves.\
> **Important:** This is a project guide, not an agent instruction file.
> It is intentionally named `AGENTIC_FLOW_PROJECT_ROADMAP.md`, not
> `AGENT.md` or `agent.md`.

------------------------------------------------------------------------

## 1. Project overview

### 1.1 What is Agentic Flow?

Agentic Flow is an open-source, AI-powered **Agentic Workflow Builder**.
It is intended to let users describe a task in natural language and turn
that description into a structured, editable and eventually executable
workflow.

Instead of requiring users to manually design every step, select every
tool and define every connection, Agentic Flow aims to understand the
user's goal, identify the required operations, plan a suitable workflow,
select available nodes and tools, generate a workflow graph, and present
that graph in a visual editor.

Users should be able to inspect and modify the generated workflow before
running it. When execution is supported, the platform should run the
workflow, show progress and results, manage resource usage, and provide
quality and operational insights.

Agentic Flow is not intended to be only a chatbot that suggests steps.
Its major objective is to connect **natural-language understanding,
workflow planning, reusable nodes, external tools, visual workflow
design, and controlled workflow execution** in one platform.

### 1.2 The problem we are solving

Building an automation or agentic workflow today can require users to:

-   Understand workflow concepts such as triggers, actions, conditions,
    branches and data connections.
-   Know which application or API provides the operation they need.
-   Configure integrations and credentials.
-   Manually connect nodes and map data between them.
-   Understand execution order and handle errors.
-   Estimate and control LLM and service costs.
-   Inspect logs and determine why a workflow failed.

This creates a steep learning curve and makes workflow creation
time-consuming, especially for users who know the task they want to
accomplish but do not know how to design the automation.

Agentic Flow aims to reduce this complexity by allowing users to explain
the desired outcome in natural language. The system assists with
requirement clarification, workflow planning, node and action selection,
workflow generation, visual editing and, in later stages, execution and
monitoring.

### 1.3 Major objectives

1.  **Natural-language workflow creation:** Convert user requirements
    into structured workflow designs.
2.  **Requirement understanding:** Identify intent, required operations,
    inputs, outputs, constraints and ambiguities.
3.  **Reusable node architecture:** Maintain a registry of reusable node
    definitions and their available actions.
4.  **AI-assisted planning:** Plan workflows using supported nodes,
    actions, integrations and templates.
5.  **Visual workflow editing:** Let users inspect, edit, configure and
    connect workflow nodes.
6.  **External application connectivity:** Make services such as Gmail,
    Slack, GitHub, Google Drive and Notion available through an
    integration layer, initially using Composio.
7.  **Workflow execution:** Execute supported workflow graphs and show
    execution progress and results.
8.  **Cost awareness:** Track LLM usage, estimate costs and enforce
    configurable budgets.
9.  **Quality evaluation:** Evaluate generated workflows for relevance,
    completeness, efficiency, safety and reliability.
10. **Observability:** Provide traces, metrics, logs, events and alerts.
11. **Security and trust:** Protect prompts, credentials, connected
    accounts, user data and execution operations.
12. **Extensibility:** Keep the architecture modular so new models,
    nodes, tools, templates and execution capabilities can be added
    without redesigning the whole application.

------------------------------------------------------------------------

## 2. Product scope and development principles

### 2.1 What the product should become

The intended end-to-end experience is:

1.  A user describes a task or starts from a template.
2.  Agentic Flow interprets the requirement and identifies missing
    information.
3.  The system asks follow-up questions when necessary.
4.  The AI guidance engine plans a solution using capabilities known to
    the platform.
5.  The workflow generator produces structured nodes, edges, ports,
    configurations and metadata.
6.  Validation and evaluation identify structural or logical problems.
7.  The user reviews and edits the workflow in the visual canvas.
8.  The user connects supported external applications and configures
    actions.
9.  The execution engine runs the workflow.
10. The platform displays node status, outputs, logs, traces, cost and
    evaluation information.

Not every step needs to exist in the first prototype. The product is
built incrementally.

### 2.2 What the first implementation is

The current first milestone is deliberately small:

-   A basic prompt text area.
-   An initially empty React Flow canvas.
-   An LLM configuration sufficient to call the selected model.
-   A backend endpoint that accepts a user prompt.
-   LLM-generated workflow JSON.
-   A defined initial JSON contract.
-   Frontend rendering of generated nodes and edges on the canvas.

**First milestone flow:**

`User prompt → FastAPI → LLM → workflow JSON → schema validation → Next.js/React Flow canvas`

The first milestone is not expected to include full workflow execution,
Composio, a complete security platform, DeepEval, OpenTelemetry, budget
enforcement, multi-user permissions or production deployment.

Basic engineering hygiene still applies from the beginning: keep secrets
out of source control, use environment variables, validate inputs,
return safe errors and avoid logging credentials.

### 2.3 Development principles

-   Build the smallest useful version of a feature before extending it.
-   Implement in dependency order, from foundational and low-complexity
    capabilities to more advanced capabilities.
-   Do not implement an architectural layer merely because it appears
    early in the architecture diagram.
-   Keep the architecture layers represented, but implement each layer
    when its dependencies exist.
-   Avoid speculative files and empty modules for distant phases.
-   Define shared data contracts before parallel implementation depends
    on them.
-   Prefer clear interfaces between modules over tightly coupled code.
-   Validate each milestone with a working end-to-end demonstration.
-   Revisit and change the roadmap when implementation discoveries
    justify it.

------------------------------------------------------------------------

## 3. Architecture reference

The architecture diagrams define the target system. They describe the
main layers and technologies, not a mandatory development sequence.

The architecture includes:

1.  **User Input & Interface** --- natural-language prompt, templates,
    file input and user customization.
2.  **Security Layer (Protection & Trust)** --- prompt-injection
    protection, credential management, data privacy and access control.
3.  **Requirement Analysis Layer** --- intent understanding, requirement
    extraction, follow-up questions and suggestions.
4.  **AI Guidance Engine** --- workflow planning, node/tool selection,
    template use and optimization.
5.  **Workflow Output** --- generated workflow, validation results and
    quality information.
6.  **Visual Editor & Execution** --- visual editing, running workflows
    and real-time monitoring.
7.  **Workflow Execution Engine** --- graph parsing/planning, node
    execution, LangChain/LangGraph orchestration and state management;
    includes the budget-engine concept in the diagram.
8.  **Integrations Layer** --- Composio and external
    applications/services.
9.  **LLM Model Config** --- multi-model configuration and provider
    support.
10. **Template Library** --- ready-to-use workflows for different
    domains.
11. **Data & Storage Layer** --- PostgreSQL, Redis and Qdrant.
12. **Monitoring & Observability** --- OpenTelemetry, traces, metrics,
    dashboards, logs, events and alerts.
13. **Evaluation Engine** --- DeepEval-based workflow quality
    evaluation.
14. **Node Library (Reusable Components)** --- reusable Input/Output,
    AI, Tools/Integrations, Logic, Memory/Knowledge and Data Processing
    nodes.

> **Numbering note:** The supplied architecture image repeats the number
> 10 for the Template Library and Data & Storage Layer. This document
> uses the layer names rather than relying on diagram numbering. The
> image contains 14 named architectural areas when the Node Library is
> counted separately.

### 3.1 Technologies shown in the architecture

  ---------------------------------------------------------------------
  Area                               Technologies shown / intended
  ---------------------------------- ----------------------------------
  Frontend                           Next.js, React, TypeScript, React
                                     Flow

  Backend                            Python, FastAPI, Pydantic

  Security                           Pydantic, OpenBao

  Requirement analysis               LLM, Pydantic

  AI guidance                        LangChain, LangGraph

  Execution                          Custom Python DAG executor,
                                     LangChain/LangGraph where
                                     appropriate

  Integrations                       Composio, REST APIs, OAuth

  LLM configuration                  LiteLLM; Gemini, OpenAI, Claude
                                     and other supported providers

  Storage                            PostgreSQL, Redis, Qdrant

  Monitoring                         OpenTelemetry, Grafana

  Evaluation                         DeepEval

  Node system                        Custom node registry and reusable
                                     node definitions

  Templates                          Department/domain-based workflow
                                     templates
  ---------------------------------------------------------------------

Technology choices are architectural intentions, not a requirement to
introduce every dependency immediately. Confirm current SDK
capabilities, licensing, API behavior and project needs before
implementation.

------------------------------------------------------------------------

## 4. How the two developers will work

### 4.1 Module-based ownership, not frontend/backend ownership

The team consists of two developers: **Sanjay and Sakthi**.

Work is divided by complete functional modules, not by technology
layers. Avoid assigning one person "all backend" and the other "all
frontend."

For example:

-   One developer may own the Requirement Analysis module end to end.
-   The other may own the Node Library module end to end.
-   A module owner is responsible for its design, implementation,
    required UI/API/logic, tests, documentation and integration.
-   The other developer must still understand the module's purpose,
    interfaces and important design decisions.

A module may contain backend code, frontend components, schemas, tests
and documentation. Its owner coordinates any work that crosses those
boundaries.

### 4.2 Shared responsibilities

Both developers should participate in:

-   Understanding the full architecture and end-to-end user journey.
-   Agreeing shared schemas and API contracts.
-   Reviewing important architecture decisions.
-   Understanding the two critical concepts selected for each phase.
-   Integration testing across module boundaries.
-   Reviewing each other's work.
-   Updating this roadmap when scope or dependencies change.

### 4.3 Suggested workflow for every phase

1.  **Understand:** Read the phase goal, relevant architecture layers
    and dependencies.
2.  **Discuss:** Both developers explain the feature and agree on
    expected behavior.
3.  **Define contracts:** Agree data structures, API boundaries, events
    and error behavior.
4.  **Assign modules:** Give each complete module one clear owner.
5.  **Implement:** Owners build and test their modules independently.
6.  **Review:** The other developer reviews the behavior and interface,
    not just code style.
7.  **Integrate:** Connect the modules and run an end-to-end test.
8.  **Demonstrate:** Show the working feature using a realistic example.
9.  **Update:** Record completed work, known limitations and changes to
    the next phase.

### 4.4 Git collaboration

Recommended branch approach:

-   `main` --- stable project baseline.
-   `testing` --- integration branch.
-   `feature/<module-name>` --- a branch for a specific module or agreed
    unit of work.

Both developers should work in their own local clone/workspace. Use pull
requests to integrate module work. Keep API keys, OAuth secrets and
other credentials out of Git. Use `.env.example` to document required
environment variables without real values.

The repository owner retains administrative control. Collaborators
should receive only the repository permissions needed for their work.

------------------------------------------------------------------------

## 5. Implementation roadmap --- dependency-ordered phases

This roadmap preserves the architectural scope while arranging work from
foundational and relatively simple capabilities to more complex
dependent capabilities. The phases are **provisional planning units**,
not immutable milestones. They can be split, combined, reordered or
renamed after technical discovery.

Each phase identifies functional module ownership. The proposed
Sanjay/Sakthi allocation is a starting point and can be changed by
mutual agreement.

### Phase 1 --- User Input & Interface: initial prototype

**Architecture area:** User Input & Interface, initial Workflow Output
and LLM connection.

**Goal:** Prove the basic prompt-to-visual-workflow loop.

  -----------------------------------------------------------------------
  Functional module       Owner                   Scope
  ----------------------- ----------------------- -----------------------
  Prompt Interface        Sakthi                  Prompt text area,
                                                  submission and basic
                                                  interaction

  Workflow Canvas         Sakthi                  Empty React Flow canvas
  Foundation                                      and basic canvas layout

  LLM Workflow Generation Sanjay                  Model call, prompt
                                                  processing and initial
                                                  JSON generation

  Workflow API Contract   Sanjay                  Request/response
                                                  contract and initial
                                                  schema validation
  -----------------------------------------------------------------------

**Both must understand:** 1. How natural-language prompts are passed to
an LLM and converted into structured JSON. 2. How nodes and edges in the
JSON are rendered by React Flow.

**Acceptance criteria:** - User can enter and submit a prompt. - Backend
receives the prompt and calls the configured LLM. - Backend returns
structured workflow JSON. - JSON is validated against the initial
schema. - Frontend renders the generated nodes and connections. - Empty
canvas remains usable when no workflow has been generated.

**Not in scope:** Full node registry, external integrations, actual
workflow execution, complete security architecture, full monitoring or
budget enforcement.

### Phase 2 --- Workflow data structure and schema

**Architecture areas:** Workflow Output and the data contracts used by
the Node Library and Visual Editor.

**Goal:** Establish a shared, extensible workflow contract before adding
many node types.

  -----------------------------------------------------------------------
  Functional module       Owner                   Scope
  ----------------------- ----------------------- -----------------------
  Workflow Schema         Sanjay                  Workflow identity,
                                                  version, metadata and
                                                  graph structure

  Node/Edge/Port Schemas  Sanjay                  Node data, edge
                                                  endpoints and
                                                  input/output ports

  Schema Validation       Sanjay                  Pydantic validation and
                                                  useful validation
                                                  errors

  Frontend Workflow Types Sakthi                  Matching TypeScript
                                                  interfaces

  Workflow Normalization  Sakthi                  Convert API data into
                                                  consistent canvas data

  Contract Examples       Both                    Agree valid and invalid
                                                  example workflows
  -----------------------------------------------------------------------

**Both must understand:** 1. Relationship between workflow, node, edge,
port and node configuration. 2. How Pydantic models and TypeScript types
remain compatible.

**Acceptance criteria:** A versioned, documented workflow contract with
example JSON and validation tests.

### Phase 3 --- Node Library and Node Registry

**Architecture area:** Node Library (Reusable Components).

**Goal:** Define which node types the platform supports and make them
discoverable.

  -----------------------------------------------------------------------
  Functional module       Owner                   Scope
  ----------------------- ----------------------- -----------------------
  Node Registry           Sanjay                  Register, retrieve and
                                                  manage node definitions

  Node Definition Model   Sanjay                  IDs, names,
                                                  descriptions,
                                                  categories, metadata
                                                  and ports

  Node Catalog            Sakthi                  Browse and search
                                                  available nodes

  Node Categories         Sakthi                  Input/Output, AI,
                                                  Tools, Logic,
                                                  Memory/Knowledge, Data
                                                  Processing

  Reusable Visual Node    Sakthi                  Render node types
  Components                                      consistently

  Node Discovery Contract Both                    Define how frontend and
                                                  AI retrieve supported
                                                  definitions
  -----------------------------------------------------------------------

**Both must understand:** 1. Difference between node definition, node
registry, node catalog and visual node component. 2. How a new node can
be added without rewriting the workflow generator or canvas.

**Acceptance criteria:** The platform can register a node, list it,
display it and resolve it by a stable node type/ID.

### Phase 4 --- Basic node rendering and canvas interactions

**Architecture area:** Visual Editor & Execution.

**Goal:** Make the canvas useful for manual workflow design, not just
display.

  -----------------------------------------------------------------------
  Functional module       Owner                   Scope
  ----------------------- ----------------------- -----------------------
  Canvas Interaction      Sakthi                  Drag, drop, select,
                                                  move, zoom and pan

  Node Rendering          Sakthi                  Render registered node
                                                  types

  Connection Handles      Sakthi                  Display input/output
                                                  ports and create edges

  Node Placement Service  Sanjay                  Validate and persist
                                                  graph position data
                                                  where needed

  Graph Consistency Rules Sanjay                  Check node/edge
                                                  references and basic
                                                  graph integrity

  Canvas Data             Both                    Keep visual graph and
  Synchronization                                 workflow JSON
                                                  synchronized
  -----------------------------------------------------------------------

**Both must understand:** 1. React Flow's node/edge model and the
platform's workflow schema. 2. How canvas changes are translated into
persistent workflow changes.

**Acceptance criteria:** Users can add, move, connect and remove basic
nodes without corrupting the workflow graph.

### Phase 5 --- Node Actions and Configuration

**Architecture area:** Node Library and Workflow Output.

**Goal:** Define what each node can do and what parameters an action
requires.

  -----------------------------------------------------------------------
  Functional module       Owner                   Scope
  ----------------------- ----------------------- -----------------------
  Action Registry         Sanjay                  Register and retrieve
                                                  actions

  Action Definition       Sanjay                  Action ID, description,
  Schema                                          parameters, required
                                                  fields and outputs

  Configuration           Sanjay                  Validate action
  Validation                                      configuration against
                                                  its schema

  Action Selector         Sakthi                  Choose an action for a
                                                  node

  Dynamic Configuration   Sakthi                  Generate fields from
  Form                                            action definitions

  Node Configuration      Sakthi                  Edit and inspect node
  Panel                                           settings
  -----------------------------------------------------------------------

**Both must understand:** 1. Difference between a node, an action and an
action configuration. 2. How action schemas drive dynamic forms and
later execution.

**Acceptance criteria:** A user can select a registered node, choose one
of its actions and configure valid parameters.

### Phase 6 --- Requirement Analysis Layer

**Architecture area:** Requirement Analysis.

**Goal:** Understand the user's actual intent and clarify incomplete
requests before workflow planning.

  -----------------------------------------------------------------------
  Functional module       Owner                   Scope
  ----------------------- ----------------------- -----------------------
  Intent Analysis         Sanjay                  Identify the user's
                                                  intended outcome

  Requirement Extraction  Sanjay                  Extract operations,
                                                  entities, inputs,
                                                  outputs and constraints

  Requirement Structuring Sanjay                  Produce a typed
                                                  requirement
                                                  specification

  Ambiguity Detection     Sakthi                  Identify missing or
                                                  contradictory details

  Follow-up Question      Sakthi                  Ask and collect
  Experience                                      clarifications

  Requirement Summary and Sakthi                  Let users inspect and
  Confirmation                                    confirm interpreted
                                                  requirements
  -----------------------------------------------------------------------

**Technologies:** LLM and Pydantic.

**Both must understand:** 1. Intent recognition versus requirement
extraction. 2. When the system should ask a follow-up question instead
of guessing.

**Acceptance criteria:** A prompt can become a structured requirement
specification, with clarification when essential details are missing.

### Phase 7 --- LLM Model Configuration

**Architecture area:** LLM Model Config.

**Goal:** Support a consistent way to configure and call different model
providers.

  -----------------------------------------------------------------------
  Functional module       Owner                   Scope
  ----------------------- ----------------------- -----------------------
  Provider Registry       Sanjay                  Register supported
                                                  model providers

  Unified Model Gateway   Sanjay                  Common interface for
                                                  model requests

  Model Routing           Sanjay                  Select models for
                                                  supported tasks

  Provider/Model Settings Sakthi                  Configure and select
  UI                                              providers/models

  Task-to-Model           Sakthi                  Configure model
  Preferences                                     preferences by task

  Model Configuration     Both                    Agree supported
  Contract                                        settings and secure
                                                  credential handling
  -----------------------------------------------------------------------

**Technologies:** LiteLLM and supported providers such as Gemini, OpenAI
and Claude.

**Both must understand:** 1. Provider versus model versus gateway versus
router. 2. How model configuration differs from budget-aware model
selection.

**Acceptance criteria:** The same application feature can call supported
providers through a common interface without provider-specific logic
spread throughout the application.

### Phase 8 --- AI Guidance Engine

**Architecture area:** AI Guidance Engine.

**Goal:** Plan a workflow using the confirmed requirements and the
platform's registered capabilities.

  -----------------------------------------------------------------------
  Functional module       Owner                   Scope
  ----------------------- ----------------------- -----------------------
  Workflow Planning       Sanjay                  Build a logical
                                                  sequence of steps

  Node Selection          Sanjay                  Select supported nodes
                                                  from the registry

  Action Selection        Sanjay                  Select compatible
                                                  registered actions

  Planning Context        Sanjay                  Supply requirement,
  Builder                                         node and action context

  Plan Preview            Sakthi                  Display proposed
                                                  workflow steps

  Template Suggestions    Sakthi                  Present relevant
                                                  template
                                                  recommendations

  Planning Feedback       Sakthi                  Let users request
                                                  changes to the proposed
                                                  plan
  -----------------------------------------------------------------------

**Technologies:** LangChain and LangGraph where they provide a clear
benefit.

**Both must understand:** 1. Workflow planning versus JSON generation
versus execution. 2. How the planner is constrained by registered nodes
and actions instead of inventing unsupported capabilities.

**Acceptance criteria:** The system can produce an inspectable plan
whose steps refer to supported platform capabilities.

### Phase 9 --- Workflow Output, Validation and Quality Review

**Architecture area:** Workflow Output.

**Goal:** Convert a plan into a valid workflow graph and identify errors
before the user relies on it.

  -----------------------------------------------------------------------
  Functional module       Owner                   Scope
  ----------------------- ----------------------- -----------------------
  Workflow JSON Generator Sanjay                  Generate nodes, edges,
                                                  ports and
                                                  configurations

  Node/Action Resolver    Sanjay                  Resolve generated
                                                  references against
                                                  registries

  Graph Builder           Sanjay                  Build the final
                                                  workflow graph

  Structural Validator    Sanjay                  Validate schema,
                                                  references and required
                                                  fields

  Workflow Preview        Sakthi                  Display generated
                                                  workflow

  Validation Results      Sakthi                  Display errors and
                                                  warnings

  Quality Summary         Sakthi                  Display available
                                                  review/validation
                                                  information
  -----------------------------------------------------------------------

**Both must understand:** 1. Structural validity versus logical
correctness. 2. How generation errors should be reported and corrected.

**Acceptance criteria:** The generated workflow is valid against the
shared schema, references known nodes/actions and can be rendered.

### Phase 10 --- Template Library

**Architecture area:** Template Library.

**Goal:** Provide reusable workflow designs for common tasks.

  -----------------------------------------------------------------------
  Functional module       Owner                   Scope
  ----------------------- ----------------------- -----------------------
  Template Registry       Sanjay                  Register and retrieve
                                                  templates

  Template Schema and     Sanjay                  Define template
  Variables                                       parameters and versions

  Template Catalog        Sakthi                  Browse, search and
                                                  filter templates

  Template Details        Sakthi                  Display purpose,
                                                  requirements and
                                                  included steps

  Template Customization  Both                    Replace template
                                                  variables and configure
                                                  actions

  Import Template to      Both                    Convert a selected
  Canvas                                          template into an
                                                  editable workflow
  -----------------------------------------------------------------------

**Template domains:** Software Development, DevOps & Deployment, QA &
Testing, Data Analytics, Research & Development, Project Management,
Marketing and Customer Support.

**Both must understand:** 1. Template versus generated workflow. 2. How
template variables map to registered nodes, actions and workflow
configuration.

**Acceptance criteria:** A user can select a template, configure its
inputs and open it as an editable workflow.

### Phase 11 --- Integrations Layer and Composio

**Architecture area:** Integrations Layer.

**Goal:** Make external applications and their operations available as
workflow actions.

  -----------------------------------------------------------------------
  Functional module       Owner                   Scope
  ----------------------- ----------------------- -----------------------
  Provider-independent    Sanjay                  Common provider
  Integration Interface                           contract

  Tool Discovery and      Sanjay                  Convert provider tools
  Normalization                                   into standard action
                                                  definitions

  Composio Connector      Sanjay                  Connect to Composio and
                                                  discover supported
                                                  tools

  Integration Catalog     Sakthi                  Display available
                                                  applications

  Connection Experience   Sakthi                  Guide users through
                                                  connecting applications

  Connected Accounts      Sakthi                  Show connection state
  Interface                                       and available accounts

  Tool/Action Selection   Sakthi                  Browse and select
                                                  external actions

  Integration-to-Node     Both                    Make external actions
  Mapping                                         compatible with the
                                                  node/action registry
  -----------------------------------------------------------------------

**Technologies:** Composio, REST APIs and OAuth.

**Initial examples:** Gmail, Slack, GitHub, Google Drive and Notion.

**Both must understand:** 1. Provider, application, connected account,
tool and workflow action. 2. How authentication and tool discovery work,
and how external tools become registered actions.

**Acceptance criteria:** A user can connect a supported application,
discover its tools and configure a supported tool action in a workflow.

### Phase 12 --- Workflow Execution Engine

**Architecture area:** Workflow Execution Engine.

**Goal:** Run a workflow graph using the registered node and action
implementations.

  ---------------------------------------------------------------------------
  Functional module    Owner                Scope
  -------------------- -------------------- ---------------------------------
  Graph Parser         Sanjay               Parse and validate the graph for
                                            execution

  Execution Planner    Sanjay               Determine valid execution order

  Node Executor        Sanjay               Execute individual node
                                            implementations

  Action Dispatcher    Sanjay               Dispatch registered actions,
                                            including supported integrations

  Execution State      Both                 Define
  Contract                                  pending/running/success/failure
                                            states

  Execution Canvas     Sakthi               Display execution progress

  Execution Results    Sakthi               Display node outputs

  Execution Timeline   Sakthi               Show execution sequence and
                                            status
  ---------------------------------------------------------------------------

**Technologies:** Custom Python DAG executor; use LangChain/LangGraph
for appropriate agentic orchestration rather than forcing every
operation through them.

**Both must understand:** 1. Graph parsing, topological ordering and
node execution. 2. How registry definitions resolve to executable
implementations.

**Acceptance criteria:** A simple workflow can run from start to finish,
with node-level status and results.

### Phase 13 --- Data & Storage Layer

**Architecture area:** Data & Storage.

**Goal:** Persist workflows, users, execution history, cache data and
vector knowledge.

  -----------------------------------------------------------------------
  Functional module       Owner                   Scope
  ----------------------- ----------------------- -----------------------
  PostgreSQL Data Model   Sanjay                  Define persistent
                                                  entities and
                                                  relationships

  Workflow Persistence    Sanjay                  Save, load and update
                                                  workflows

  Execution History       Sanjay                  Store execution records
  Storage                                         and results

  Qdrant Knowledge        Sanjay                  Store and retrieve
  Service                                         vector data when
                                                  required

  Redis Cache Service     Sakthi                  Implement cache use
                                                  cases and integration

  Saved Workflow          Sakthi                  Browse and reopen saved
  Experience                                      workflows

  History and Knowledge   Sakthi                  Display history and
  Interfaces                                      knowledge resources

  Storage Contract        Both                    Agree data ownership
  Integration                                     and API boundaries
  -----------------------------------------------------------------------

**Technologies:** PostgreSQL, Redis and Qdrant.

**Both must understand:** 1. Relational database versus cache versus
vector database. 2. What data should be stored, cached or embedded, and
why.

**Acceptance criteria:** Workflows and execution history persist across
sessions; cache and vector features work for explicitly supported use
cases.

### Phase 14 --- Budget Engine

**Architecture area:** Budget Engine within the Workflow Execution
Engine.

**Goal:** Estimate, track and control model usage and costs.

  -----------------------------------------------------------------------
  Functional module       Owner                   Scope
  ----------------------- ----------------------- -----------------------
  Token Tracker           Sanjay                  Track input/output
                                                  tokens

  Model Pricing Registry  Sanjay                  Maintain model pricing
                                                  information

  Cost Calculator         Sanjay                  Calculate estimated and
                                                  actual cost

  Usage Aggregator        Sanjay                  Aggregate usage by
                                                  user, workflow, run and
                                                  model

  Budget Policy Manager   Sanjay                  Define limits and
                                                  thresholds

  Preflight Cost          Sanjay                  Estimate cost before
  Estimator                                       generation/execution

  Runtime Budget          Sanjay                  Enforce limits during
  Controller                                      operation

  Model Router and        Sanjay                  Apply configured
  Fallback                                        cost-aware
                                                  routing/fallback

  Budget Dashboard        Sakthi                  Display cost and usage

  Budget Settings and     Sakthi                  Configure limits and
  Alerts                                          show warnings

  Cost Breakdown          Sakthi                  Show usage by workflow
                                                  and model
  -----------------------------------------------------------------------

**Technology:** LiteLLM for model integration/usage information where
supported, plus custom budget policy and accounting modules.

**Both must understand:** 1. Token counts, model pricing and cost
calculation. 2. Preflight estimation versus runtime enforcement versus
model fallback.

**Acceptance criteria:** Usage is recorded consistently, cost estimates
are available and configured limits are enforced with clear behavior.

### Phase 15 --- Evaluation Engine

**Architecture area:** Evaluation Engine.

**Goal:** Measure whether generated workflows are relevant, complete,
efficient, safe and reliable.

  -----------------------------------------------------------------------
  Functional module       Owner                   Scope
  ----------------------- ----------------------- -----------------------
  Evaluation Orchestrator Sanjay                  Run evaluation pipeline

  Accuracy/Relevance      Sanjay                  Assess alignment with
  Evaluator                                       user requirements

  Task Completion         Sanjay                  Assess whether the
  Evaluator                                       workflow covers the
                                                  requested task

  Efficiency Evaluator    Sanjay                  Assess unnecessary
                                                  steps and workflow
                                                  efficiency

  Safety/Reliability      Sanjay                  Evaluate risk and
  Evaluator                                       reliability criteria

  Evaluation Dataset      Sakthi                  Manage representative
  Manager                                         test cases

  Evaluation Results      Sakthi                  Display scores,
  Interface                                       findings and
                                                  explanations

  Evaluation History      Sakthi                  Compare results across
                                                  versions

  Evaluation Reports      Sakthi                  Present detailed
                                                  reports
  -----------------------------------------------------------------------

**Technology:** DeepEval, supplemented by deterministic checks where
appropriate.

**Both must understand:** 1. LLM-as-a-judge evaluation versus
deterministic validation. 2. Evaluation datasets, metrics, thresholds
and reproducibility.

**Acceptance criteria:** The platform can run repeatable
workflow-quality evaluations and explain identified issues.

### Phase 16 --- Monitoring & Observability

**Architecture area:** Monitoring & Observability.

**Goal:** Observe the full lifecycle across APIs, LLM calls, nodes,
integrations and execution.

  -----------------------------------------------------------------------
  Functional module       Owner                   Scope
  ----------------------- ----------------------- -----------------------
  OpenTelemetry           Sanjay                  Initialize and
  Instrumentation                                 configure telemetry

  Trace Collection        Sanjay                  Trace requests,
                                                  workflows, nodes and
                                                  tool calls

  Metrics Collection      Sanjay                  Collect latency,
                                                  failures and usage
                                                  metrics

  Structured Logging      Sanjay                  Record useful
                                                  application events
                                                  safely

  Alert Service           Sanjay                  Identify operational
                                                  problems

  Monitoring Dashboard    Sakthi                  Display system health

  Trace Viewer            Sakthi                  Inspect workflow traces

  Metrics Dashboard       Sakthi                  Display performance
                                                  metrics

  Logs and Events Viewer  Sakthi                  Search and inspect
                                                  events

  Alerts Interface        Sakthi                  Present alerts and
                                                  insights
  -----------------------------------------------------------------------

**Technologies:** OpenTelemetry and Grafana.

**Both must understand:** 1. Logs versus metrics versus distributed
traces. 2. How a workflow run is correlated across nodes, model calls
and external services.

**Acceptance criteria:** A workflow run can be investigated through
correlated traces, metrics and logs.

### Phase 17 --- Security Layer (Protection & Trust)

**Architecture area:** Security Layer.

**Goal:** Implement complete security for the real platform resources
and operations that now exist.

  -----------------------------------------------------------------------
  Functional module       Owner                   Scope
  ----------------------- ----------------------- -----------------------
  Prompt Injection        Sanjay                  Detect and mitigate
  Protection                                      malicious prompt
                                                  instructions

  Input/Output Guard      Sanjay                  Validate and filter
                                                  unsafe or sensitive
                                                  content

  Credential and Secret   Sanjay                  Protect provider keys
  Management                                      and connected-account
                                                  credentials

  OpenBao Integration     Sanjay                  Integrate a
                                                  secrets-management
                                                  system

  Authentication and      Sanjay                  Enforce identity and
  Authorization                                   permissions

  Data Privacy and        Sakthi                  Build privacy controls
  Isolation                                       and user-facing data
                                                  settings

  Access Control          Sakthi                  Manage roles,
  Experience                                      permissions and access
                                                  visibility

  Security Audit          Sakthi                  Display security events
  Interface                                       and audit history

  Security/Monitoring     Both                    Connect security events
  Integration                                     to observability
  -----------------------------------------------------------------------

**Technologies:** Pydantic, OpenBao and appropriate
authentication/authorization mechanisms.

**Both must understand:** 1. Prompt injection, credential security,
authentication and authorization. 2. How protection applies to prompts,
workflows, integrations, storage and execution.

**Acceptance criteria:** Security controls are tested across the
platform, secrets are not exposed, and access is restricted according to
the defined permission model.

**Important:** Basic security hygiene is required from Phase 1. This
phase represents the full security layer, not the first time security is
considered.

### Phase 18 --- Advanced Execution, Reliability and Optimization

**Architecture area:** Workflow Execution Engine and Visual Editor &
Execution.

**Goal:** Extend the basic executor to support complex and recoverable
workflows.

  -----------------------------------------------------------------------
  Functional module       Owner                   Scope
  ----------------------- ----------------------- -----------------------
  Conditional Execution   Sanjay                  Branching, if/else and
                                                  switch

  Parallel Execution      Sanjay                  Execute independent
                                                  branches concurrently

  Retry Manager           Sanjay                  Configure retry
                                                  policies

  Checkpoint Manager      Sanjay                  Persist execution
                                                  checkpoints

  Recovery Manager        Sanjay                  Recover interrupted
                                                  runs

  Timeout Manager         Sanjay                  Control long-running
                                                  operations

  Execution Control       Sakthi                  Pause, resume and
  Experience                                      cancel workflows

  Recovery Interface      Sakthi                  Inspect and recover
                                                  eligible runs

  Parallel Execution      Sakthi                  Display concurrent
  Visualization                                   branches

  Debugging Experience    Both                    Inspect failures and
                                                  execution paths
  -----------------------------------------------------------------------

**Both must understand:** 1. Sequential versus conditional versus
parallel execution. 2. Retry, idempotency, checkpointing and recovery.

**Acceptance criteria:** Complex workflows can branch, run parallel
operations and recover safely from supported failures.

### Phase 19 --- Production Integration and Deployment

**Architecture areas:** All architecture layers.

**Goal:** Integrate, test, deploy and operate the complete platform.

  -----------------------------------------------------------------------
  Functional module       Owner                   Scope
  ----------------------- ----------------------- -----------------------
  Backend/Engine          Sanjay                  Deploy API and
  Deployment                                      execution services

  Database and            Sanjay                  Deploy and configure
  Infrastructure                                  data services
  Deployment                                      

  Production Secrets and  Sanjay                  Configure production
  Configuration                                   environment safely

  Frontend Deployment     Sakthi                  Deploy the user
                                                  application

  Onboarding and          Sakthi                  Provide a usable
  Workspace Experience                            first-run experience

  End-to-End Test Suite   Sanjay                  Test complete backend
                                                  and workflow journeys

  User Journey Acceptance Sakthi                  Test complete
  Tests                                           user-facing flows

  CI/CD and Release       Both                    Automate checks and
  Process                                         releases

  Production Verification Both                    Verify reliability,
                                                  security and
                                                  observability
  -----------------------------------------------------------------------

**Acceptance criteria:** The complete platform is deployed, tested,
observable and usable in its intended environment.

------------------------------------------------------------------------

## 6. Important shared architecture concepts

The following relationships must remain consistent across phases.

### 6.1 Node → Action → Integration → Execution

-   A **node** is a reusable capability or visual unit in a workflow.
-   An **action** describes an operation that a node can perform.
-   An **integration** provides access to an external application or
    service.
-   An **executor** performs the registered action at runtime.

Example:

-   Node: Gmail
-   Action: Send Email
-   Integration: Composio-connected Gmail account
-   Configuration: Recipient, subject and message body
-   Execution: The executor dispatches the configured action using the
    connected account.

### 6.2 Requirement → Plan → Workflow JSON → Visual Graph → Execution

These are different stages:

-   Requirement analysis determines what the user needs.
-   AI guidance plans how to accomplish it.
-   Workflow generation constructs the graph.
-   Validation checks the graph and its configuration.
-   The visual editor lets the user inspect and modify it.
-   The execution engine runs the graph.

Do not merge these responsibilities into one large LLM call or one
oversized service.

### 6.3 Budget engine responsibilities

The budget engine is not the same as model configuration:

-   LLM configuration makes providers and models available.
-   Budget tracking records usage.
-   Cost calculation estimates or calculates monetary cost.
-   Budget policies define allowed limits.
-   Runtime enforcement applies those limits.
-   Model routing selects an appropriate model under configured
    policies.

### 6.4 Evaluation versus monitoring

-   **Evaluation** asks whether a workflow is good and satisfies the
    requirement.
-   **Monitoring** reports what happened while the system was operating.

DeepEval does not replace runtime monitoring. OpenTelemetry does not
decide whether a workflow logically satisfies the user's intent.

### 6.5 Security versus basic validation

-   Input validation checks whether data has the expected format.
-   Prompt-injection protection addresses malicious or untrusted
    instructions.
-   Authentication verifies identity.
-   Authorization determines permitted operations.
-   Secret management protects credentials.
-   Data isolation prevents unauthorized access to another user's
    resources.

These controls are related but not interchangeable.

------------------------------------------------------------------------

## 7. How we decide whether a phase is complete

A phase should not be marked complete simply because its files have been
created.

Use this completion checklist:

-   [ ] The phase objective is implemented.
-   [ ] The module has a clear owner.
-   [ ] Shared interfaces and data contracts are documented.
-   [ ] Main success paths work.
-   [ ] Important failure paths are handled.
-   [ ] Tests have been written and passed.
-   [ ] The feature is integrated with dependent modules.
-   [ ] Both developers understand the phase's two critical concepts.
-   [ ] The working feature has been demonstrated.
-   [ ] Known limitations and follow-up work are documented.

A phase may be partially complete. Record what works and what remains
rather than marking it complete prematurely.

------------------------------------------------------------------------

## 8. Roadmap change policy

This document is a **living roadmap**, not a fixed contract.

The team may change:

-   Phase order when dependencies or implementation discoveries require
    it.
-   Phase boundaries when a phase is too large or too small.
-   Module ownership based on workload, skills and availability.
-   File names and folder structure as the codebase develops.
-   Technologies when a better-supported or more suitable choice is
    identified.
-   Acceptance criteria as the product becomes clearer.

When changing the roadmap:

1.  Explain the reason for the change.
2.  Identify affected phases and dependencies.
3.  Confirm the change together.
4.  Update this document.
5.  Keep completed work and current implementation accurate.

Do not reorganize the project merely to match this document if the
existing code has a better, working structure. The roadmap should guide
implementation, not force unnecessary rewrites.

------------------------------------------------------------------------

## 9. Immediate next steps

The current priority is to complete and verify Phase 1.

1.  Inspect the existing repository and identify what is already
    implemented.
2.  Verify prompt submission and LLM connectivity.
3.  Agree the initial workflow JSON contract.
4.  Generate a small workflow with a few nodes and edges.
5.  Validate the JSON.
6.  Render the generated workflow on the React Flow canvas.
7.  Test invalid output and API/LLM failure handling.
8.  Demonstrate the complete prompt-to-canvas flow.
9.  Then begin Phase 2 and agree the durable workflow schema.

Do not start implementing all future phase files now. Create modules
when their phase is active and their responsibilities are understood.

------------------------------------------------------------------------

## 10. Project success vision

Agentic Flow succeeds when a user who understands the task but does not
know how to build an automation can describe the desired outcome,
receive a sensible workflow design, understand and edit that design,
connect the required services, execute it safely, and inspect its
quality, cost and operational behavior.

The long-term goal is a modular, extensible, open-source agentic
workflow platform that makes workflow creation more accessible while
retaining transparency, user control, reliability and cost awareness.

------------------------------------------------------------------------

**Document owner:** Agentic Flow development team\
**Primary developers:** Sanjay and Sakthi\
**Document status:** Living project guide; update as architecture and
implementation evolve.

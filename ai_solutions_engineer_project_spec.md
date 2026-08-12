# Portfolio Project Spec: AP Invoice Triage Agent (AI Solutions Engineer track)

This is the final, locked-in version of the project, built specifically for **AI Solutions Engineer** roles (the AVP / Baker Tilly style of posting), not for research-heavy or fine-tuning-heavy roles. Every decision below was made deliberately, with the tradeoff stated explicitly, so nothing here is an accidental gap.

## Concept (unchanged)

An agent that ingests vendor invoices, extracts structured data, cross-checks against a vendor database and budget rules, flags anomalies, and drafts a payment recommendation — but never auto-approves. A human reviews and approves every payment action. Finance/accounting-flavored on purpose: it reads as directly relevant to both Baker Tilly (accounting/advisory) and bank-style AVP postings.

## What's in scope, and why

### 1. Custom RAG pipeline (not a managed Knowledge Base) — the depth signal

This is the single most differentiating piece of the project, precisely because most candidates' "RAG experience" means naive single-stage vector search, not this.

```
S3 (invoices, vendor contracts, spending policies)
   → Lambda/ECS: parse documents, chunk (your own logic, not a black box)
   → Embed each chunk (Bedrock or SageMaker-hosted embedding model)
   → Store in RDS PostgreSQL + pgvector (AWS-managed, VPC-native — satisfies data residency)

Query time:
   → Hybrid search: pgvector similarity + native tsvector/ts_rank (BM25-style keyword match), combined
   → Reranking stage (an existing open cross-encoder, called in-code or hosted on SageMaker — don't train one, just call one well)
   → Top reranked chunks passed to the LLM as grounding context
```

Own every stage. Be ready to explain, concretely: why you chunked the way you did, what hybrid search bought you over pure vector search (run this comparison and keep the numbers), and what reranking changed in your top-k results.

**Explicitly not used**: Bedrock Knowledge Bases. Not because it's bad — it's a good product — but because for a portfolio project the entire point is owning and being able to explain every stage, and Knowledge Base's embedding step is fixed to Bedrock-hosted models regardless of custom chunking/vector-store flexibility it does offer. Say this precisely in your writeup; overstating "Knowledge Base is a black box" in an interview is a correctable but avoidable stumble.

### 2. LangGraph — the orchestration logic

This is your portable, highest-demand skill — the piece that transfers to any employer regardless of cloud. Build the agent's reasoning here first, and get it working and observable *before* touching any AWS deployment layer. Don't debug agent logic and deployment infrastructure at the same time.

Tools the agent calls (exposed via MCP, see below):
- `extract_invoice_data`
- `lookup_vendor`
- `check_budget`
- `flag_duplicate`
- `retrieve_context` (calls your custom RAG pipeline above — this replaces what a Knowledge Base would have done)
- `draft_recommendation`

### 3. MCP server — the standardized tool interface

Build the tools above as an MCP server (FastMCP is the easiest path). This is what makes the tools discoverable and callable in a standardized way, independent of which agent framework or client connects to them. Test locally with an MCP client (Claude Code or Claude Desktop can connect directly) before deploying anywhere.

### 4. Bedrock — model inference + guardrails

Used narrowly and correctly: raw model invocation (Claude via Bedrock's API) for the agent's reasoning/generation steps, and Bedrock Guardrails wrapping those calls for PII filtering and blocking any auto-approval behavior. Not used for its packaged Knowledge Base RAG product (see above).

### 5. AgentCore — the deployment/runtime layer

Where the whole LangGraph agent runs once it's working locally:
- **Runtime**: hosts the agent, session isolation, auto-scaling
- **Gateway**: connects the agent to your MCP server, authenticated via OAuth or IAM SigV4 — explicitly not "no authorization," and be ready to explain that choice
- **Identity**: access control over who/what can invoke which tools
- **Memory** (optional): persist context across sessions if you want the agent to recall prior invoices from the same vendor

This is where your AWS SAA cert cashes out directly — IAM, VPC, containers, and serverless concepts you already know, applied to a new but conceptually familiar service.

### 6. IaC, CI/CD, and governance — the AVP/Baker Tilly emphasis

- Terraform or CDK for everything: VPC, RDS, S3, IAM roles (least privilege, no `AdministratorAccess`), CloudWatch log groups, container registry.
- GitHub Actions: lint/test → deploy to dev → manual approval gate → deploy to a "prod" environment.
- Audit log of every agent action tied to a user identity.
- A one-page "AI usage guardrails" doc: what the agent is and isn't allowed to do, in plain language.

### 7. Human review dashboard

Simple Next.js app: list of processed invoices, the agent's recommendation and reasoning trace, approve/reject/correct buttons, running stats including token cost per invoice. Your fullstack background, showing up directly. Keep it clean — don't over-build it.

### 8. Token efficiency (small effort, disproportionately valuable to call out)

Route cheap sub-tasks (simple field extraction) to a smaller/cheaper model, reserve the larger model for the actual reasoning step. Cache repeated context (policy text, tool schemas). Report a concrete before/after token-cost number in your writeup.



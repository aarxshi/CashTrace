# Case Study: Building an AI System That Knows When It Doesn't Know

### CashTrace — an experiment in using AI responsibly for financial investigation

Financial reconciliation seems like the kind of problem AI should be able to solve easily.

Give a model two financial records. Ask whether they match. If they don't, ask why.

The problem is that a convincing answer is not necessarily a correct one.

That became the starting point for CashTrace.

I wasn't interested in building an AI that could confidently explain every financial discrepancy. I wanted to explore a harder question:

> **How do you make AI useful in a financial workflow without allowing it to become the source of financial truth?**

---

## Where the project started

The initial problem was reconciliation.

Financial records are fragmented. A payout might include sales, fees, refunds, and adjustments before eventually appearing as a bank settlement. When the final amount doesn't match what was expected, someone has to figure out where the difference came from.

The obvious solution is to automate the explanation.

But that immediately raised a problem.

Suppose an AI sees a short settlement and says:

> "This was likely caused by a reserve."

That explanation might sound reasonable.

It might even be correct.

But unless the available financial records actually prove that a reserve was held, the system has just introduced something dangerous into the workflow: **a plausible story that could be mistaken for a fact**.

That changed how I approached the entire project.

---

# The decision that shaped CashTrace

## I stopped asking the AI to reconcile the money.

Instead, I separated the problem into two questions:

### What can the system calculate?

and:

### What does the available evidence suggest?

Those questions should not have the same answer source.

Financial calculations are deterministic.

If:

```text
Expected Settlement = Gross − Fees − Refunds
```

then the system should calculate it.

There is no reason to ask a language model to perform arithmetic that ordinary code can perform consistently and reproducibly.

AI becomes useful after that calculation.

Once the system knows:

* What should have settled
* What actually settled
* The exact difference
* The transaction context

then AI can help investigate what the difference might mean.

This became the central principle behind CashTrace:

> **AI investigates the numbers. It does not decide what the numbers are.**

---

# The harder problem was uncertainty

The most interesting design challenge wasn't detecting mismatches.

It was deciding what the system should do when it *cannot explain one with certainty*.

Most software is designed around successful outcomes.

Match.

No match.

Resolved.

But financial investigations are often messier.

Sometimes the available records strongly suggest an explanation without proving it.

Sometimes there simply isn't enough information.

Instead of forcing every transaction into a binary outcome, I introduced the idea of proof-aware conclusions.

The system can distinguish between:

* Something that is **verified by deterministic evidence**
* Something that is **explained by available supporting evidence**
* Something that is **probable but not proven**
* Something that is **still unresolved**

This may seem like a small product decision, but it changes the role of AI completely.

The model is no longer rewarded for producing an answer.

It is allowed to preserve uncertainty.

I think that is especially important in finance.

A system saying:

> "We don't have enough evidence to determine the cause."

is significantly safer than one confidently generating an explanation to fill the gap.

---

# Building for messy inputs instead of perfect demos

Another decision came from thinking about how reconciliation tools actually get used.

Most demos begin with perfectly structured data.

A CSV has exactly the expected columns. Every amount is clean. Every identifier exists.

Real financial exports are rarely that cooperative.

Different platforms might use different names for essentially the same thing.

One file might say:

```text
Gross
```

while another says:

```text
Sales
```

or:

```text
Amount
```

The same problem appears with transaction IDs, dates, fees, refunds, settlements, and channels.

Rather than making the reconciliation logic depend on one exact CSV format, I added a normalization layer.

That layer converts common variations into a consistent internal representation before reconciliation begins.

The reasoning behind this was simple:

> **The reconciliation engine should understand financial concepts, not just column names.**

This also helped create a cleaner boundary in the system.

Import logic handles messy external formats.

The reconciliation engine operates on a consistent schema.

The investigation layer works with established financial facts.

Separating those stages made the project easier to reason about and reduced the temptation to put too much intelligence into one component.

---

# Why I didn't want an AI-first architecture

There is an appealing demo version of this project where the entire workflow looks like:

```text
Financial records
      ↓
LLM
      ↓
Explanation
```

It would probably look impressive.

It would also make the system difficult to trust.

The problem isn't that LLMs are incapable of reasoning about financial data.

The problem is that they don't provide the guarantees needed for the numerical path.

They can:

* Make arithmetic mistakes
* Misinterpret context
* Invent missing information
* Produce confident explanations from incomplete evidence

So I deliberately made the AI layer downstream of the deterministic layer.

The AI never receives a blank financial problem and gets asked to solve it from scratch.

It receives the financial facts that the reconciliation engine has already established.

That creates an important boundary:

```text
Deterministic system:
"What happened according to the data?"

AI investigator:
"What might explain the part we cannot yet account for?"
```

Those responsibilities are related, but they are not interchangeable.

---

# A mismatch is not automatically a problem worth investigating

Another thing I learned while building the project was that reconciliation is not just about finding differences.

It is about deciding which differences matter.

Imagine a finance team with hundreds of exceptions.

A flat table of mismatches does not tell someone where to start.

So CashTrace prioritizes exceptions based on financial impact.

The question becomes:

> **Where should a human spend their attention first?**

This shifted the project away from being just a reconciliation tool and toward being an investigation workflow.

Instead of only reporting that something failed to match, the system can surface:

* How much money is affected
* How significant the difference is
* What evidence exists
* Whether the explanation is proven or uncertain
* What should be investigated next

The goal is not to remove humans from the process.

It is to make human investigation more focused.

---

# What evaluation changed about the project

One of the things I wanted to avoid was judging the project based only on whether the interface looked convincing.

Financial software can produce an extremely polished dashboard while quietly making bad decisions underneath.

So I included evaluation around the actual reconciliation pipeline.

The synthetic dataset used in the project allows the system to measure:

* Transactions processed
* Exact matches
* Exceptions
* Automatic verification rate
* Financial variance
* Amount at risk

The current dataset contains **192 bank-feed transactions and 37 settlement deposits**, with **33 deterministic exact matches and 4 partial or short settlements**. The reconciliation engine automatically verifies **89.2%** of deposits while surfacing **₹1,780.73 in settlement variance** rather than forcing those cases into incorrect matches.

The important part of that result isn't the percentage.

It's what happens to the remaining cases.

They stay visible.

They are not silently converted into successful matches just to improve a metric.

That was a deliberate choice.

---

# The tradeoff I chose

CashTrace does not try to automate every financial decision.

That means some outcomes remain unresolved.

From a product perspective, that can feel unsatisfying.

An AI system that always has an explanation looks more intelligent than one that occasionally says:

> "Additional evidence is required."

But I think the second system is more useful in this context.

The purpose of a financial control workflow isn't to maximize the number of automated answers.

It is to maximize the number of answers you can trust.

That distinction shaped nearly every decision in the project.

---

# What I would improve next

CashTrace is a working exploration rather than a finished production system.

The next things I would focus on are:

### Stronger schema detection

The current normalization layer handles common column variations, but production imports would need more robust validation, previewing, and user confirmation.

### Better evidence retrieval

The AI investigator currently works from the available transaction context. A more mature version could retrieve historical investigations, settlement policies, platform documentation, and related transactions.

### Investigation feedback loops

Human investigators should be able to confirm or reject explanations, allowing the system to build a structured history of resolved exception patterns.

### More financial sources

The same approach could extend beyond settlement reconciliation to invoices, accounts receivable, accounts payable, and inventory movements.

### Production controls

A real financial system would require stronger authentication, data access controls, immutable audit logs, and integrations with accounting platforms.

---

# What I learned

The biggest lesson from building CashTrace was that **AI architecture is often more important than the model itself**.

It would have been easy to add an LLM to the beginning of the pipeline and ask it to solve the whole problem.

The more interesting engineering question was:

> **Where should AI be allowed to make decisions, and where should it be explicitly prevented from doing so?**

For this project, my answer was:

* Let deterministic systems handle what can be calculated.
* Let evidence determine what can be proven.
* Let AI help investigate what remains unclear.
* Never allow confidence to become a substitute for evidence.

CashTrace is ultimately less about replacing a financial operator and more about giving one a better starting point for investigation.

Because when money doesn't add up, the most useful system is not necessarily the one that produces the fastest answer.

> **It's the one that clearly separates what happened, what can be proven, what is only likely, and what still needs to be investigated.**

<!-- Advisory only: this output is never a merge gate, never an approval. -->
You are extracting a structured list of actions from an Aave governance
forum post. The untrusted input below is the raw forum text (fetched from
governance.aave.com for the topic named in the proposal's `discussions:`
front matter).

Extract every distinct funded/transferred/approved action mentioned in the
post: an amount of an asset moving to or from an address, an allowance
being set, refreshed, or cancelled.

Respond with STRICT JSON ONLY — no markdown, no prose, no code fence, no
explanation before or after. The exact shape:

{"forum": [
  {"action": "<short verb phrase, e.g. 'Reimburse', 'Approve', 'Refresh Allowance'>",
   "asset": "<token symbol as written, e.g. 'aEthLidoGHO'>",
   "amount": "<the number as written, e.g. '50,000' or '0.5M' or 'Current Balance + buffer'>",
   "recipient": "<name or address as written, or null>",
   "network": "<network name as written, e.g. 'Ethereum'>"}
]}

Rules:
- One entry per distinct action. If the post is vague or open-ended about an
  amount (e.g. "current balance + buffer"), still include it with that exact
  text as "amount" — never invent a number.
- Only extract what is actually written. Never guess.
- If you cannot produce valid JSON for any reason, respond with exactly:
  {"forum": [], "error": "<one short reason>"}

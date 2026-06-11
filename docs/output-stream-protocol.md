# Verified Output Stream: Interlock Commitments + Recomputation Certificate (v4)

## Properties

The protocol gives the verifier four properties about a compute node's network output, and gives the prover one:

- **P1 — Complete attribution.** Every byte leaving the node belongs to exactly one packet in one time bucket; there is no unattributed wire traffic.
- **P2 — No rewriting.** What the prover can later claim about past traffic is fixed at the time the traffic occurred, before any challenge is known.
- **P3 — Measurable explanation.** For any randomly sampled output, the verifier obtains a sound upper bound U on the information in it that is not explained by a declared computation on a committed input.
- **P4 — Timeline integrity.** Traffic volume and bucket numbering are anchored to wall-clock time; history cannot be stretched, replayed, or run ahead.
- **P5 (prover) — Confidentiality.** The verifier learns packet lengths, request IDs, timing, and U — never payloads, keys, or weights.

Scope: single request→response pairs; size/time-distribution accounting deferred.

**Interlock assumptions:**
1. **Reset-free by construction** — the HMAC key and bucket counter share a battery-backed volatile domain, so state loss permanently ends the certificate stream rather than restarting it (re-commissioning with a new key required). Availability-for-simplicity trade: battery failure bricks verification, not traffic.
2. **Speedup resistant** beyond ~2× — slowdown needs no assumption; it is directly visible in the verifier's anchor log.
3. The HMAC key `k` (shared with the verifier) stays secret.
4. Its ~70 KB of working memory is tamper-proof. The interlock retains only the current second; all history lives in prover storage.

## Commitment hierarchy

Three levels; a challenge response opens one path from root to packet.

```
certificate   =  HMAC_k( header ‖ H(input bucket hashes) ‖ H(output bucket hashes) )    — 1/second
bucket hash   =  H( (len₁, id₁, pkt_hash₁) ‖ (len₂, id₂, pkt_hash₂) ‖ … )               — 1/ms/direction
packet hash   =  H( len ‖ id ‖ [recomp_commitment ‖] H(ciphertext) )                    — per packet
```

The ordered `(length, id, pkt_hash)` records in a bucket hash reconstruct the byte stream exactly (P1); `H(ciphertext)` is kept as a separable leaf so it can serve as a recomputation-certificate public input without revealing the ciphertext.

**Input packet:** `length ‖ request_id ‖ recomp_commitment ‖ ciphertext`, where `recomp_commitment = H(key material for this request and its response)` and ciphertext = `AES_K(prompt tokens)`.
**Output packet:** `length ‖ request_id ‖ ciphertext` = `AES_K(response tokens)`.
Packets carry no hash fields — the interlock computes all hashes itself, so there is nothing to mismatch and no hash channel to police.

**Certificate fields** (fixed-width serialization):

```
version ‖ interlock_id ‖ bucket_start ‖ num_buckets(=1000) ‖ H(in-seq) ‖ H(out-seq) ‖ nonce ‖ HMAC_k(…)
```

| Field | Why it exists |
|---|---|
| `version`, `interlock_id` | bind the MAC to this protocol and device |
| `bucket_start`, `num_buckets` | place this second on the bucket timeline; consecutive certificates must tile it — a gap the prover cannot fill is a violation (P2, P4) |
| the two sequence hashes | commit 2000 bucket hashes without shipping them |
| `nonce` | latest verifier nonce seen; proves the certificate postdates it (P4) |
| `length`, `request_id` in bucket records | locate byte x; bind response to request without payload exposure (P1, P5) |
| `H(ciphertext)` | the H1 the recomputation certificate binds to (P3, P5) |
| `recomp_commitment` | the H2 pinning the keys, fixed at request time (P3) |

Every certificate field is exactly prover-predictable, so the prover can byte-audit certificates as they arrive. The interlock's total covert-output surface is the nonce-latch timing (≤1 bit per nonce update) plus the HMAC tag itself (coverable by cut-and-choose, below).

## Steady state (no verifier present)

Every **millisecond**, per direction: close the bucket, hash its records (`H(ε)` if empty), emit a boundary marker into the stream (excluded from hashes) so the prover's transcript reproduces the interlock's packet→bucket assignment. Drop — never hashed, never emitted — any packet over `S_max` or violating ID order: strictly increasing across the session inbound; strictly increasing within each bucket outbound (prover pre-sorts; the output comparator resets per bucket because responses finish out of order). Drops leave no trace in commitments and need none — a dropped packet never exits the node, so it carries no exfiltration risk; the prover monitors drops operationally by comparing its own two switch logs.

Every **second**: emit the certificate, discard the bucket hashes. The prover stores certificates, bucket-hash sequences (~166 GB/30 days both directions), and the full transcript.

**Nonce latch:** the verifier occasionally sends a plaintext nonce inbound; the interlock latches the latest and echoes it in every certificate. No authentication needed: the verifier credits only nonces it generated, so injecting or replaying nonces is indistinguishable from dropping them — both read as staleness. The interlock generates MACs but never verifies one.

## Challenge

1. **Anchor.** Verifier sends a fresh nonce; prover returns the next certificate echoing it, stamping current bucket `B` within `[t_nonce, t_receipt]`. Verifier logs the anchor and checks counter monotonicity and counter rate vs. wall clock.
2. **Select.** Uniform `(bucket y, byte x)` over `[B − window, B] × [0, C)`, where `C` is per-bucket capacity (100 KB at 100 MB/s line rate). Uniform-over-capacity is size-weighted sampling: every transmitted byte is equally likely to be challenged; an `x` past the bucket's content is a cheap liveness check.
3. **Open** (entirely from prover storage): the stored certificate covering `y`, its 1000-entry output bucket-hash sequence, bucket `y`'s record list; then for the hit packet, its header and `H(ciphertext)` — and the same opening for the matching input packet in bucket `w` (certificate, sequence, records, header, `H(ciphertext)`, `recomp_commitment`). Under the ZKP option no ciphertext is ever sent to the verifier.
4. **Recompute.** The prover supplies a recomputation certificate (next section) binding to the opened values.
5. **Verify**, in order: (a) both certificates' MACs and `interlock_id` against the anchor log; (b) sequences hash to certificate commitments; (c) record lists hash to the two bucket hashes; (d) byte `x` falls in the claimed packet per cumulative lengths; (e) input binding — bucket `w` ≤ bucket `y`, request IDs match, this ID has explained no other response; (f) the recomputation certificate verifies against `(H1_in, H2, H1_out)`, yielding U.

Input binding closes the fabricated-input cheat (a "request" containing the covert output would recompute with zero surprisal); single-use closes its amortized variant (one innocent request explaining many responses).

## Recomputation certificate

A recomputation certificate attests, for one challenged pair: *"the response tokens whose ciphertext hashes to `H1_out`, decrypted under keys hashing to `H2`, carry at most U bits not explained by the declared computation D applied to the prompt tokens whose ciphertext hashes to `H1_in`."* All three recomputation options (prover recomputation, verifier recomputation, ZKP) implement this same interface; what differs is who is trusted for faithful execution.

### ZKP instantiation (per the infproof implementation)

![ZKP option: the workload path is unchanged (verifier — prover frontend — interlock — prover compute); at challenge time the prover compute generates the proof π, which the frontend forwards to the verifier alongside the interlock certificates. No additional hardware.](fig-zkp.png){ width=100% }

- **Public inputs:** U (in bits), `H1_in`, `H1_out`, `H2`, the model-weight commitment `R_W`, and the claim structure from which the verifier *compiles its own constraint system* — it never trusts prover-supplied constraints.
- **Hidden witness:** weights, prompt tokens, response tokens, logits, all intermediate activations (committed behind Merkle roots `R_W`, `R_p1`, `R_p2`).
- **Proven statement:** `SHA256(AES(tokens_in, key)) = H1_in`, `SHA256(AES(tokens_out, key)) = H1_out`, `SHA256(key) = H2`; the same committed tokens feed the embedding lookup and the hidden output selection (MaxClaim), so the bound applies to the *transmitted* tokens, not free-floating ones; logits = D(W, x) for the declared architecture; per-token probabilities follow the pinned hardware-noise model `Q_t(o_t) ∝ exp(−(v* − ℓ_{o_t})²/s_c)` with all rounding pushed upward, so `U_proved ≥ U_true`.
- **Why (H1, H2) suffice:** they are the only bridge needed between the interlock's world (hashes of wire bytes) and the circuit's world (token values). H1 values are leaves of interlock-committed packet hashes; H2 was committed inside the input packet at request time — before the response existed, so keys cannot be chosen retroactively to fit a covert payload.
- **Parameters (current implementation):** Ligero over the Goldilocks field with Reed–Solomon + BLAKE3 Merkle commitments — hash-based throughout, no trusted setup, post-quantum. Proof ≈ 150 MB, verification ≈ 13 min for a 32-layer 7B model; the token-binding constraints add ~10⁶ constraints (~0.01% of the proof).

### Prover-recomputation instantiation (Option 1, mediated by a recomputation interlock)

The prover's own hardware recomputes inside a verifier enclosure; a second, simpler interlock mediates all data crossing the enclosure boundary and emits the certificate.

![Prover recomputation option: the same workload track, plus a parallel recomputation track — the frontend stages the challenged pair through a second (stateless) interlock to the recomputation compute inside the verifier enclosure.](fig-prover-recomp.png){ width=100% }

**Setup (before the workload phase):** the recomputation node enters the enclosure loaded only with pre-committed data (weights, execution engine). It must not be — or share state with — the node that ran the workload: a node that remembers the challenged response can replay any covert payload at probability 1 and launder it as "explained." If hardware is reused across challenge sessions, memory is wiped between them.

**Challenge-time ingress is gated by commitments.** The recomputation interlock feeds the enclosure exactly three things:
1. the input-packet ciphertext, which it hashes itself and checks against `H1_in`;
2. the cryptographic material (key, nonces), which it hashes and checks against `H2`. This ingress is what makes H2 load-bearing here: the node needs the key to decrypt the prompt and to compute per-position encrypted output units, but the key material enters *after* the response exists — unpinned, the staged blob could smuggle the answers in (e.g., contain the response itself alongside the true key). H2 was fixed in the input packet at request time, before the response existed, so the staged material cannot be chosen retroactively to fit a covert payload;
3. the challenged output ciphertext, one unit at a time, each revealed only after the node commits its prediction for that position.

**Scoring runs in ciphertext space** — the interlock never decrypts. At each position the node commits a table of `(ciphertext_unit → probability)` entries; the interlock checks the table is a sub-distribution (`Σ q ≤ 1`, with the residual mass defined as uniform over unlisted unit values, so misses score ~32+ bits rather than ∞ and Q stays a valid distribution — without this check the node could commit probability ≈1 for everything); then it looks up the actual unit, records the surprisal, and reveals the unit. Predicting ciphertext units well requires the true key and the true computation, so the scoring itself needs no key check. A hardware-friendly variant restricts probabilities to dyadic values: the node commits integer (or quarter-bit) surprisals `s_j`, the interlock checks `Σ 2^(−s_j) ≤ 1` by shift-and-add, and U accumulates without any log circuit, costing the honest prover ≤1 bit/token. Optionally, tables have a fixed size every step (dummy entries at floor probability, randomized order) so the interlock learns nothing from distribution shape.

**Certificate:** `m = ("recomp-v1", recomp_interlock_id, challenge_nonce, H1_in, H2, H1_out, n_units, U)`, `τ = HMAC_k₂(m)`, where `H1_in` and `H2` were verified against the actual staged bytes and `H1_out` is the interlock's own hash of the ciphertext it revealed — all recomputed from bytes, none trusted from the prover. The verifier checks these equal the values opened from the network certificates. Binding to `challenge_nonce` makes the device **stateless**: no buckets, no timeline, no battery-backed counter — its assumptions reduce to key secrecy and side-channel hardening. Every field is prover-predictable, so the byte-audit and slot-bound cut-and-choose carry over with slot = nonce. There is no duration field — a measured-time value has slack the prover cannot predict (the same covert-channel reasoning that removed drop counters); the verifier times the challenge on its own clock.

Both instantiations bind the same triple `(H1_in, H2, H1_out)` and end at the same interface; they use H2 oppositely — the ZKP to connect plaintext tokens to wire bytes inside the circuit, Option 1 to pin what may enter the enclosure after the response exists.

**End-to-end chain:** wire bytes → packet hash → bucket hash → HMAC certificate (fixed within 1 s of transmission) → H1/H2 → in-circuit tokens → U. The verifier needs nothing but its anchor log, the opened commitments, and the proof.

**Worked sizes:** anchor certificate ~150 B → challenge ~12 B → opening ≈ 2 certificates + two 32 KB hash sequences + two record lists (~48 B/packet) + two headers with hashes (~100 B) → recomputation certificate ~150 MB (ZKP option). Everything outside the proof verifies with a few hundred hashes over ~100 KB.

**Certificate-release audit (optional):** since every certificate field is prover-predictable, a prover worried about covert bits in HMAC tags can release challenge-time tags via slot-bound cut-and-choose: the verifier binds one commitment per certificate slot *before* revealing its own τ′ — it must never act as an unrestricted HMAC oracle.

## Spec decisions

1. **One key commitment per pair.** `H2 = H(key material)` covers both the request and its response, carried in the input packet (matching the paper's packet format). Per-direction keys would require a second commitment field.
2. **Hash alignment.** `H(ciphertext)` must be the hash the ZKP circuit proves — SHA-256 — so the interlock's payload-hashing block is SHA-256. Bucket and certificate levels never enter the circuit and could differ, but everything stays SHA-256 for one gateware core.
3. **AES mode.** The cipher must allow position-addressable fixed-width token units (e.g., AES-CTR with fixed bytes-per-token serialization) so recomputation options can address individual token ciphertexts without decrypting the stream.

## Suggested parameters

`H` = SHA-256; MAC = HMAC-SHA-256 (pre-shared `k`); bucket = 1 ms; certificate period = 1 s; `request_id` = 64-bit; `S_max` = deployment-set; per-bucket capacity `C` = 100 KB; challenge window = 30 days (prover-side storage).

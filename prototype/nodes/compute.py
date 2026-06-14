"""Prover compute node (also the recomputation engine).   [diagram: Prover compute]

Untrusted. Serves two ops over a socket:
  workload : request packet in  ->  response packet out   (runs the LLM)
  score    : (prompt, tokens)   ->  per-token argmax       (the verifier uses this to recompute U)

The interlock forwards workload requests here; the verifier calls `score` directly
for recomputation (one model instance backs both — a stateless re-scoring, so it
can't replay a remembered output). Set MOCK=1 to run without torch.
"""
import os

from common import P, serve, ids_to_bytes, PORT_COMPUTE

MOCK = os.environ.get("MOCK") == "1"

if MOCK:
    def gen(prompt, n):
        return [3681, 338, 278, 7483, 310], "Paris is the capital of France."

    def score(prompt, tokens):
        return list(tokens)             # honest: predicted == actual
else:
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer
    MODEL = os.environ.get("MODEL_DIR", "/home/claude/models/llama-2-7b-hf")
    _tok = AutoTokenizer.from_pretrained(MODEL)
    if _tok.pad_token is None:
        _tok.pad_token = _tok.eos_token
    _model = AutoModelForCausalLM.from_pretrained(MODEL, dtype=torch.float16).cuda().eval()

    @torch.no_grad()
    def gen(prompt, n):
        ids = _tok(prompt, return_tensors="pt").input_ids.cuda()
        out = _model.generate(ids, max_new_tokens=n, do_sample=False,
                              pad_token_id=_tok.eos_token_id)
        new = out[0, ids.shape[1]:].tolist()
        return new, _tok.decode(new)

    @torch.no_grad()
    def score(prompt, tokens):
        ids = _tok(prompt, return_tensors="pt").input_ids.cuda()
        resp = torch.tensor(tokens, device="cuda").unsqueeze(0)
        seq = torch.cat([ids, resp], dim=1)
        start = ids.shape[1] - 1
        return _model(seq).logits[0, start:start + resp.shape[1]].argmax(-1).tolist()


def handler(req):
    if req["op"] == "workload":                       # request packet -> response packet
        pkt = bytes.fromhex(req["request_packet"])
        p = P.parse_packet("in", pkt)
        toks, text = gen(p["ciphertext"].decode(errors="replace"), req.get("max_new", 48))
        out = P.output_packet(p["request_id"], ids_to_bytes(toks))
        return {"response_packet": out.hex(), "text": text}
    if req["op"] == "score":                          # recomputation
        return {"argmax": score(req["prompt"], req["tokens"])}
    return {"error": "unknown op"}


if __name__ == "__main__":
    serve(PORT_COMPUTE, handler, "compute")
